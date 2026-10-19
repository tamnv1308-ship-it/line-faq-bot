"""One dialog handler per browser context, including late/preserved pages.

No CO actions, navigation, retries or raw dialog text in diagnostic logs.
"""
import re
import weakref


class ContextDialogs:
    def __init__(self, context, diagnostic=None):
        self.sessions = weakref.WeakKeyDictionary()
        self.seen = weakref.WeakSet()
        self.diagnostic = diagnostic
        context.on('dialog', self.handle)
        # Keep the listener until context closure has completed.
        context.on('close', lambda *_: self.sessions.clear())

    def begin(self, page, job_id):
        alerts = []
        self.sessions[page] = (str(job_id), alerts)
        return alerts

    def emit(self, event, kind, job_id):
        if self.diagnostic is None:return
        safe_id = job_id if re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', job_id or '') else ''
        try:self.diagnostic({'event': event, 'dialog_type': kind, 'job_id': safe_id})
        except Exception:pass

    def handle(self, dialog):
        # Mark before handling: callbacks can re-enter while pumping browser events.
        if dialog in self.seen:return
        self.seen.add(dialog)
        job_id = ''
        kind = 'unknown'
        try:
            kind = dialog.type
            session = self.sessions.get(dialog.page)
            if session:
                job_id, alerts = session
                alerts.append(str(dialog.message)[:2500])
                del alerts[:-20]
        except Exception:pass
        try:
            # Alerts are informational. Never accept confirm/prompt/beforeunload.
            if kind == 'alert':dialog.accept()
            else:dialog.dismiss()
        except Exception as error:
            # A user/site may have closed it already. Never retry handling it and
            # never let an event callback kill the worker or change a job outcome.
            text = str(error).lower()
            gone = any(value in text for value in
                       ('no dialog is showing', 'already handled', 'has been closed'))
            self.emit('dialog_already_closed' if gone else 'dialog_handler_error', kind, job_id)


def install_dialogs(context, diagnostic=None):
    # This is a Python-side attachment, not state injected into the website.
    existing = getattr(context, '_co_context_dialogs', None)
    if isinstance(existing, ContextDialogs):return existing
    manager = ContextDialogs(context, diagnostic)
    context._co_context_dialogs = manager
    return manager
