const express = require('express');
const app = express();

app.use(express.json());

const signedUrlRoutes = require('./routes/signedUrl.routes');
const errorHandler = require('./middleware/errorHandler');

app.use('/storage', signedUrlRoutes);
app.use(errorHandler);

module.exports = app;