const { Storage } = require('@google-cloud/storage');
const {
  GCS_BUCKET,
  MAX_FILE_SIZE,
  UPLOAD_URL_EXPIRY,
  DOWNLOAD_URL_EXPIRY,
  ALLOWED_CONTENT_TYPES,
} = require('../config');

const storage = new Storage();

/**
 * Generate a signed POST policy URL for uploading a file to GCS.
 * - Enforces allowed content types
 * - Enforces max file size (25MB)
 * - URL expires in 15 minutes
 */
async function generateUploadUrl(fileName, contentType, fileSize) {
  if (!ALLOWED_CONTENT_TYPES.includes(contentType)) {
    const err = new Error(`Content type "${contentType}" is not allowed.`);
    err.status = 400;
    throw err;
  }

  if (fileSize > MAX_FILE_SIZE) {
    const err = new Error(`File size ${fileSize} exceeds the 25MB limit.`);
    err.status = 400;
    throw err;
  }

  const [policy] = await storage
    .bucket(GCS_BUCKET)
    .file(fileName)
    .generateSignedPostPolicyV4({
      expires: Date.now() + UPLOAD_URL_EXPIRY,
      conditions: [
        ['content-length-range', 1, MAX_FILE_SIZE],
        ['eq', '$Content-Type', contentType],
      ],
      fields: { 'Content-Type': contentType },
    });

  return policy;
}

/**
 * Generate a signed GET URL for downloading a file from GCS.
 * - URL expires in 1 hour
 */
async function generateDownloadUrl(fileName) {
  const [url] = await storage
    .bucket(GCS_BUCKET)
    .file(fileName)
    .getSignedUrl({
      action: 'read',
      expires: Date.now() + DOWNLOAD_URL_EXPIRY,
    });

  return url;
}

module.exports = { generateUploadUrl, generateDownloadUrl };