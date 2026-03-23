"""
Notification Windows (toast WinRT) + sauvegarde HTML locale.
Utilise PowerShell WinRT — aucune dépendance Python externe.
"""
import os
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ_PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    _TZ_PARIS = timezone(timedelta(hours=1))


def _today_paris() -> date:
    return datetime.now(_TZ_PARIS).date()


def _toast_ps(title: str, message: str) -> str:
    """Script PowerShell pour afficher un toast WinRT."""
    t = title.replace("'", "`'")
    m = message.replace("'", "`'")
    return f"""
$ErrorActionPreference = 'SilentlyContinue'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]
$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{t}')) | Out-Null
$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{m}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Revue Evenements IA').Show($toast)
Start-Sleep -Seconds 1
"""


def notify_toast(title: str, message: str):
    """Affiche un toast Windows natif via PowerShell WinRT."""
    try:
        result = subprocess.run(
            ["pwsh", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", _toast_ps(title, message)],
            capture_output=True, timeout=10, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            print("[NOTIFIER] Toast affiché")
        else:
            print(f"[NOTIFIER] Toast erreur: {result.stderr[:200]}")
    except Exception as e:
        print(f"[NOTIFIER] Toast échec: {e}")


def deliver(events: list[dict]) -> bool:
    """Sauvegarde HTML locale + toast Windows + ouverture navigateur."""
    try:
        from mailer import build_html
        today = _today_paris()
        today_str = today.strftime("%Y-%m-%d")
        today_label = today.strftime("%d/%m/%Y")

        out_dir = Path(__file__).parent / "rapports"
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / f"revue_evenements_ia_{today_str}.html"
        out_file.write_text(build_html(events), encoding="utf-8")

        notify_toast(
            title=f"Événements IA — {today_label}",
            message=f"{len(events)} événements collectés.",
        )
        os.startfile(str(out_file))
        print(f"[NOTIFIER] Rapport: {out_file}")
        return True
    except Exception as e:
        print(f"[NOTIFIER] Erreur: {e}")
        return False
