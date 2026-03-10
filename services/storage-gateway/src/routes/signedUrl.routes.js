const express = require('express');
const router = express.Router();
const { generateUploadUrl, generateDownloadUrl } = require('../services/signedUrl.service');
const { requireRole } = require('../middleware/rbac');

/**
 * POST /storage/upload-url
 * Body: { fileName, contentType, fileSize }
 * Returns a signed POST policy URL for uploading to GCS.
 */
router.post(
  '/upload-url',
  requireRole(['client', 'attorney', 'admin']),
  async (req, res, next) => {
    const { fileName, contentType, fileSize } = req.body;

    if (!fileName || !contentType || !fileSize) {
      return res.status(400).json({ error: 'fileName, contentType, and fileSize are required.' });
    }

    try {
      const policy = await generateUploadUrl(fileName, contentType, fileSize);
      res.status(200).json({ uploadPolicy: policy });
    } catch (err) {
      next(err);
    }
  }
);

/**
 * GET /storage/download-url/:fileId
 * Returns a signed GET URL for downloading a file from GCS.
 * RBAC: only users with appropriate roles can access.
 */
router.get(
  '/download-url/:fileId',
  requireRole(['client', 'attorney', 'admin']),
  async (req, res, next) => {
    const { fileId } = req.params;

    try {
      // TODO: add ownership check — verify req.user owns or has access to fileId
      const url = await generateDownloadUrl(fileId);
      res.status(200).json({ downloadUrl: url });
    } catch (err) {
      next(err);
    }
  }
);

module.exports = router;