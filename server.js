// server.js
const express = require('express');
const crypto = require('crypto');
const path = require('path');
const app = express();
const port = 3000;

let storedOTP = ''; // In-memory OTP

// Serve static files (like otp-generator.html and index.html)
app.use(express.static(path.join(__dirname)));

// Enable JSON parsing for POST
app.use(express.json());

// GET /generate-otp - create and return OTP
app.get('/generate-otp', (req, res) => {
  const otp = crypto.randomInt(100000, 999999).toString();
  storedOTP = otp;
  console.log(`Generated OTP: ${otp}`);
  res.json({ otp });
});

// POST /validate-otp - validate OTP
app.post('/validate-otp', (req, res) => {
  const { otp } = req.body;
  res.json({ valid: otp === storedOTP });
});

app.get('/otp-generator', (req, res) => {
  res.sendFile(path.join(__dirname, 'otp-generator.html'));
});

// Start server
app.listen(port, () => {
  console.log(`✅ Server running at http://localhost:${port}`);
});
