const { generateUploadUrl, generateDownloadUrl } = require('../src/services/signedUrl.service');

// Mock @google-cloud/storage
jest.mock('@google-cloud/storage', () => {
  const mockGetSignedUrl = jest.fn().mockResolvedValue(['https://signed-download-url.example.com']);
  const mockGenerateSignedPostPolicyV4 = jest.fn().mockResolvedValue([
    { url: 'https://signed-upload-url.example.com', fields: {} },
  ]);

  return {
    Storage: jest.fn().mockImplementation(() => ({
      bucket: jest.fn().mockReturnValue({
        file: jest.fn().mockReturnValue({
          getSignedUrl: mockGetSignedUrl,
          generateSignedPostPolicyV4: mockGenerateSignedPostPolicyV4,
        }),
      }),
    })),
  };
});

describe('generateUploadUrl', () => {
  it('returns a signed upload policy for a valid PDF', async () => {
    const result = await generateUploadUrl('test.pdf', 'application/pdf', 1024);
    expect(result).toHaveProperty('url');
  });

  it('throws 400 for a disallowed content type', async () => {
    await expect(
      generateUploadUrl('test.exe', 'application/exe', 1024)
    ).rejects.toMatchObject({ status: 400 });
  });

  it('throws 400 when file size exceeds 25MB', async () => {
    const tooBig = 26 * 1024 * 1024;
    await expect(
      generateUploadUrl('big.pdf', 'application/pdf', tooBig)
    ).rejects.toMatchObject({ status: 400 });
  });
});

describe('generateDownloadUrl', () => {
  it('returns a signed download URL', async () => {
    const url = await generateDownloadUrl('some/file.pdf');
    expect(typeof url).toBe('string');
    expect(url).toContain('https://');
  });
});