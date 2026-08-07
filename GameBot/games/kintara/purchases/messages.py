from __future__ import annotations

from core.locale_text import localized_literal


def cookie_guide(lang: str = "fa") -> str:
    if lang == "en":
        return (
            "<b>Connect your Kintara account</b>\n\n"
            "Your payment is approved. Send the Kintara session cookie to start the service.\n\n"
            "How to find it on desktop:\n"
            "1. Sign in at kintara.gg\n"
            "2. Press F12 and open Application\n"
            "3. Open Cookies, then kintara.gg\n"
            "4. Copy the value of __Host-kintara_session\n\n"
            "You may send either the eyJ... value or the complete "
            "__Host-kintara_session=eyJ... form.\n\n"
            "The incoming message is deleted immediately. The stored credential is encrypted "
            "and is never displayed in the admin panel."
        )
    return localized_literal("kintara.purchase.cookie_guide")


def approved_waiting_cookie(lang: str = "fa") -> str:
    if lang == "en":
        return "Your payment was approved. Send the Kintara connection cookie using the guide below."
    return localized_literal("kintara.purchase.approved_waiting_cookie")
