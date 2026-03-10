const request = require('supertest');
const app = require('../src/app');

// Mock the service layer
jest.mock('../src/services/signedUrl.service', () => ({
  generateUploadUrl: jest.fn().mockResolvedValue({
    url: 'https://signed-upload.example.com',
    fields: {},
  }),
  generateDownloadUrl: jest.fn().mockResolvedValue('https://signed-download.example.com'),
}));

// Mock RBAC to inject a user on every request
jest.mock('../src/middleware/rbac', () => ({
  requireRole: () => (req, res, next) => {
    req.user = { id: 'user-1', role: 'attorney' };
    next();
  },
}));

describe('POST /storage/upload-url', () => {
  it('returns 200 with an uploadPolicy for valid input', async () => {
    const res = await request(app)
      .post('/storage/upload-url')
      .send({ fileName: 'doc.pdf', contentType: 'application/pdf', fileSize: 1024 });

    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('uploadPolicy');
  });

  it('returns 400 when required fields are missing', async () => {
    const res = await request(app)
      .post('/storage/upload-url')
      .send({ fileName: 'doc.pdf' });

    expect(res.status).toBe(400);
  });
});

describe('GET /storage/download-url/:fileId', () => {
  it('returns 200 with a downloadUrl', async () => {
    const res = await request(app).get('/storage/download-url/some%2Ffile.pdf');

    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('downloadUrl');
  });
});