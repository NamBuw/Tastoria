# Frontend + Android delivery

`/` is the public landing page; `/gioi-thieu/` remains a compatible alias. `/bep` opens the authenticated app. Login and registration are optional links on the public site. Native startup still requires a session.

## Pipeline

1. `.github/workflows/frontend.yml` runs on PRs and main pushes: clean npm install, TypeScript, ESLint, palette contrast, Expo web export, and Chromium routing/UI smoke checks with mocked account data.
2. Only a successful main run advances `deploy/frontend` to the tested commit, using the repository-scoped Actions token. PR jobs cannot promote a release.
3. The server's user systemd timer polls that branch through its existing SSH Git remote every two minutes. A lock prevents overlapping releases. It verifies the promoted commit belongs to main, then uses a dedicated checkout under `~/.local/state/tastoria-cd/checkout`.
4. The server first builds and checks the nginx image and restarts only nginx. It then builds a signed APK using the existing local release key and publishes it atomically under `dist/tastoria-<version>.apk`. The landing shows the Android release as pending until the APK exists; a slow Android build never blocks web publication. No backend migrations, catalog imports, or model updates run.
5. `TASTORIA_WEB_TAG` tracks the frontend independently of `TASTORIA_IMAGE_TAG`. Failed web health checks restore the previous frontend image. The deployed commit is recorded only on success.

The existing Android project uses the repository's local release-signing plugin. No signing secrets or production environment files are stored in GitHub. Increment `expo.version` and `android.versionCode` together for Android releases; update the landing download URL accordingly. Previously installed Android apps must install the new APK; this is not an OTA updater.

## Server setup

Copy `deploy/systemd/tastoria-frontend.*` to `~/.config/systemd/user/`, then run:

```sh
systemctl --user daemon-reload
systemctl --user enable --now tastoria-frontend.timer
loginctl enable-linger "$USER"
```

The unit assumes the live deployment is `~/NamBuw/Tastoria/deploy`. Set `TASTORIA_LIVE_DEPLOY` if moving it. The server requires Node 22+, Python, Docker, Java 17, the Android SDK and the existing `~/.config/tastoria/keystore.env` signing configuration. API URL defaults to `https://tastoria.ctslab.net/api/v1`.

Logs: `journalctl --user -u tastoria-frontend.service`. Pause releases: `systemctl --user stop tastoria-frontend.timer`. GitHub Actions must have permission to write the promotion branch. A missing promotion branch or failing build leaves the live version unchanged.

This pipeline covers frontend and Android. Backend/model deployment remains the separate existing `deploy.sh` workflow.
