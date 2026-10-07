"""Local web API and static frontend for the fictional student mailbox."""

import json
import logging
import os
import queue
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from university_agent_security.agent.withdrawal_agent import (
    ToolActivityCallback,
    WestbridgeWithdrawalAgent,
)
from university_agent_security.tools.email_tool import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SENDER,
    STUDENT_INBOX_ADDRESS,
    EmailTool,
)

LOGGER = logging.getLogger(__name__)
STUDENT_ID = 1
FRONTEND_DIRECTORY = Path(__file__).resolve().parents[3] / "frontend"


class WithdrawalAgent(Protocol):
    def process_withdrawal_request(
        self,
        email_id: int,
        student_id: int,
        email_body_addendum: str | None = None,
    ) -> str: ...


class StudentEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(default=STUDENT_INBOX_ADDRESS, max_length=254)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=50_000)
    injection_text: str | None = Field(default=None, max_length=10_000)


class SecurityModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["protected", "vulnerable"]


def create_app(
    email_tool: EmailTool | None = None,
    agent_factory: Callable[[ToolActivityCallback, bool], WithdrawalAgent]
    | None = None,
) -> FastAPI:
    """Create the local app, allowing tool/model injection for tests."""
    mailbox = email_tool or EmailTool(DEFAULT_DATABASE_PATH)
    activity_queues: dict[str, queue.Queue[dict[str, object] | None]] = {}
    activity_lock = threading.Lock()
    security_mode_lock = threading.Lock()
    security_mode: Literal["protected", "vulnerable"] = "protected"

    def create_agent(
        on_tool_activity: ToolActivityCallback, vulnerable_mode: bool
    ) -> WithdrawalAgent:
        if agent_factory is not None:
            return agent_factory(on_tool_activity, vulnerable_mode)

        from langchain_ollama import ChatOllama

        model = ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
        )
        return WestbridgeWithdrawalAgent(
            model=model,
            database_path=mailbox.database_path,
            on_tool_activity=on_tool_activity,
            vulnerable_mode=vulnerable_mode,
        )

    def publish_activity(
        job_id: str,
        message: str,
        tool: str | None = None,
        *,
        status: str = "working",
        done: bool = False,
    ) -> None:
        with activity_lock:
            event_queue = activity_queues.get(job_id)
        if event_queue is not None:
            event_queue.put(
                {"message": message, "tool": tool, "status": status, "done": done}
            )

    def process_email(
        job_id: str,
        email_id: int,
        mode: Literal["protected", "vulnerable"],
        injection_text: str | None,
    ) -> None:
        status_by_operation = {
            ("Email Tool", "read_email"): "Reading email",
            ("Student Tool", "lookup_student"): "Checking student eligibility",
            ("Student Tool", "check_enrollment"): "Checking student eligibility",
            (
                "Student Tool",
                "check_withdrawal_eligibility",
            ): "Checking student eligibility",
            ("Document Tool", "search_documents"): "Searching withdrawal policy",
            ("Ticket Tool", "create_ticket"): "Creating support ticket",
            ("Email Tool", "send_email"): "Sending response",
        }

        def on_tool_activity(tool_name: str, operation: str) -> None:
            message = status_by_operation.get(
                (tool_name, operation), f"Using {tool_name}"
            )
            publish_activity(job_id, message, tool_name)

        try:
            create_agent(
                on_tool_activity, mode == "vulnerable"
            ).process_withdrawal_request(
                email_id=email_id,
                student_id=STUDENT_ID,
                email_body_addendum=injection_text,
            )
            inbox_result = mailbox.list_student_emails(STUDENT_ID, "inbox")
            reply_was_saved = inbox_result.success and any(
                email.email_id > email_id
                and DEFAULT_SENDER.casefold() in email.sender.casefold()
                for email in inbox_result.emails
            )
            if reply_was_saved:
                publish_activity(
                    job_id, "Request completed", status="completed", done=True
                )
            else:
                publish_activity(
                    job_id,
                    "Request could not be completed",
                    status="error",
                    done=True,
                )
        except Exception:
            LOGGER.exception("Mailbox agent failed after storing email_id=%s", email_id)
            publish_activity(
                job_id,
                "Request could not be completed",
                status="error",
                done=True,
            )
        finally:
            with activity_lock:
                event_queue = activity_queues.get(job_id)
            if event_queue is not None:
                event_queue.put(None)

    application = FastAPI(
        title="Westbridge Student Mail",
        description="Fictional, local-only student mailbox API.",
        version="0.1.0",
    )

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "Westbridge Student Mail"}

    @application.get("/api/security-mode")
    def get_security_mode() -> dict[str, str]:
        with security_mode_lock:
            return {"mode": security_mode}

    @application.post("/api/security-mode")
    def set_security_mode(request: SecurityModeRequest) -> dict[str, str]:
        nonlocal security_mode
        with security_mode_lock:
            security_mode = request.mode
        LOGGER.info("security_demo_mode_changed mode=%s", request.mode)
        return {"mode": request.mode}

    @application.get("/api/mailbox/inbox")
    def inbox() -> dict[str, object]:
        result = mailbox.list_student_emails(STUDENT_ID, "inbox")
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {"emails": [email.to_dict() for email in result.emails]}

    @application.get("/api/mailbox/sent")
    def sent() -> dict[str, object]:
        result = mailbox.list_student_emails(STUDENT_ID, "sent")
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {"emails": [email.to_dict() for email in result.emails]}

    @application.get("/api/emails/{email_id}")
    def read_email(email_id: int) -> dict[str, object]:
        result = mailbox.read_student_email(STUDENT_ID, email_id)
        if not result.success:
            status_code = 404 if result.error_code == "not_found" else 422
            raise HTTPException(status_code=status_code, detail=result.error)
        return {"email": result.emails[0].to_dict()}

    @application.post("/api/emails", status_code=202)
    def send_email(request: StudentEmailRequest) -> dict[str, object]:
        if request.recipient.strip().casefold() != STUDENT_INBOX_ADDRESS:
            raise HTTPException(
                status_code=422,
                detail=f"Mail can only be sent to {STUDENT_INBOX_ADDRESS}",
            )

        stored = mailbox.submit_student_email(STUDENT_ID, request.subject, request.body)
        if not stored.success:
            status_code = 404 if stored.error_code == "not_found" else 422
            raise HTTPException(status_code=status_code, detail=stored.error)
        student_email = stored.emails[0]
        injection_text = (
            request.injection_text.strip()
            if request.injection_text and request.injection_text.strip()
            else None
        )
        with security_mode_lock:
            request_mode = security_mode
        job_id = uuid.uuid4().hex
        event_queue: queue.Queue[dict[str, object] | None] = queue.Queue()
        with activity_lock:
            activity_queues[job_id] = event_queue
        publish_activity(job_id, "Email received")
        threading.Thread(
            target=process_email,
            args=(job_id, student_email.email_id, request_mode, injection_text),
            daemon=True,
            name=f"westbridge-agent-{job_id[:8]}",
        ).start()
        return {
            "sent_email": student_email.to_dict(),
            "job_id": job_id,
            "security_mode": request_mode,
        }

    @application.get("/api/activity/{job_id}")
    def activity_stream(job_id: str) -> StreamingResponse:
        with activity_lock:
            event_queue = activity_queues.get(job_id)
        if event_queue is None:
            raise HTTPException(status_code=404, detail="Activity session not found")

        def events():
            try:
                while True:
                    try:
                        event = event_queue.get(timeout=15)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["done"]:
                        break
            finally:
                with activity_lock:
                    activity_queues.pop(job_id, None)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    application.mount(
        "/",
        StaticFiles(directory=FRONTEND_DIRECTORY, html=True),
        name="frontend",
    )
    return application


app = create_app()
