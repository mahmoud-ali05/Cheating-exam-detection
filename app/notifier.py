"""Native OS notification (optional - uses `plyer` if installed)."""


def system_notify(title: str, message: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=message,
                            app_name="Cheating Alert System", timeout=6)
    except Exception:  # plyer missing or no notification daemon - the in-app toast still shows
        pass
