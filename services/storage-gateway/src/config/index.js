module.exports = {
  GCS_BUCKET: process.env.GCS_BUCKET_NAME,
  REGION: process.env.GCS_REGION || 'us-central1',
  MAX_FILE_SIZE: 25 * 1024 * 1024, // 25MB
  UPLOAD_URL_EXPIRY: 15 * 60 * 1000,   // 15 minutes in ms
  DOWNLOAD_URL_EXPIRY: 60 * 60 * 1000, // 1 hour in ms
  ALLOWED_CONTENT_TYPES: [
    'application/pdf',
    'image/jpeg',
    'image/png',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ],
};