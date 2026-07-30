from __future__ import annotations


TRANSFER_TEXT = (
    "Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận "
    "Chăm sóc Khách hàng.Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ."
)
TRANSFER_HTML = (
    "<p>Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận "
    "Chăm sóc Khách hàng.</p><p>Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.</p>"
)
TRANSFER_PLAIN_SOURCE = (
    "Xin lỗi vì sự bất tiện.  Yêu cầu của Quý Khách đã được chuyển đến bộ phận "
    "Chăm sóc Khách hàng.\nVui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ."
)


def trace(
    trace_id: str,
    session_id: str | None,
    turn: object,
    timestamp: str,
    response: object,
    *,
    freshdesk_id: str | None = None,
    title: str = "IBFT synthetic",
) -> dict:
    return {
        "id": trace_id,
        "sessionId": session_id,
        "timestamp": timestamp,
        "environment": "default",
        "metadata": {"turn": turn},
        "input": {
            "source": "ticket",
            "other_info": {
                "freshdesk_id": freshdesk_id if freshdesk_id is not None else session_id,
                "title": title,
                "meta": {"domain": "ibft"},
                "comments": [],
            },
        },
        "output": {
            "response": response,
            "agents_used": ["customer-service"],
            "elapsed_s": 1.0,
        },
    }
