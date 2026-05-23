from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from google_auth_oauthlib.flow import InstalledAppFlow


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class Command(BaseCommand):
    help = "Start a local OAuth flow and print a YouTube refresh token."

    def handle(self, *args, **options):
        if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
            raise CommandError("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")

        client_config = {
            "installed": {
                "client_id": settings.YOUTUBE_CLIENT_ID,
                "client_secret": settings.YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

        flow = InstalledAppFlow.from_client_config(client_config, scopes=[YOUTUBE_UPLOAD_SCOPE])
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            access_type="offline",
            prompt="consent",
        )

        if not credentials.refresh_token:
            raise CommandError("Google did not return a refresh token. Revoke the app and retry with prompt=consent.")

        self.stdout.write(self.style.SUCCESS("Copy this into YOUTUBE_REFRESH_TOKEN in your .env file:"))
        self.stdout.write(credentials.refresh_token)
