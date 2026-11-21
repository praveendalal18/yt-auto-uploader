#!/usr/bin/env bash
# Deploys the uploader as a Cloud Run Job that runs every 3 hours.
# Run from the project folder, after `gcloud auth login`.
# Edit the 4 values below first.
set -euo pipefail

PROJECT_ID="yt-auto-uploader-praveen"     # your Google Cloud project ID
REGION="asia-south1"                      # Mumbai
SHEET_ID="PASTE_SHEET_ID"
DRIVE_FOLDER_ID="PASTE_DRIVE_FOLDER_ID"

JOB="yt-uploader"
SECRET="yt-uploader-tokens"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# 1) Store the tokens file as a secret (re-running adds a new version)
if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  gcloud secrets versions add "$SECRET" --data-file=tokens/tokens.json
else
  gcloud secrets create "$SECRET" --data-file=tokens/tokens.json --replication-policy=automatic
fi
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null

# 2) Build + deploy the job
gcloud run jobs deploy "$JOB" --source . --region "$REGION" \
  --memory 1Gi --cpu 1 --task-timeout 3600 --max-retries 0 \
  --set-env-vars "SHEET_ID=${SHEET_ID},DRIVE_FOLDER_ID=${DRIVE_FOLDER_ID},TOKENS_FILE=/secrets/tokens.json" \
  --set-secrets "/secrets/tokens.json=${SECRET}:latest"

# 3) Schedule it: every 3 hours, India time
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/run.invoker" >/dev/null
URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB}:run"
if gcloud scheduler jobs describe "${JOB}-every-3h" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${JOB}-every-3h" --location "$REGION" \
    --schedule "0 */3 * * *" --time-zone "Asia/Kolkata" --uri "$URI" --http-method POST \
    --oauth-service-account-email "$RUNTIME_SA"
else
  gcloud scheduler jobs create http "${JOB}-every-3h" --location "$REGION" \
    --schedule "0 */3 * * *" --time-zone "Asia/Kolkata" --uri "$URI" --http-method POST \
    --oauth-service-account-email "$RUNTIME_SA"
fi

echo
echo "Done. Run it once now with:"
echo "  gcloud run jobs execute $JOB --region $REGION --wait"
