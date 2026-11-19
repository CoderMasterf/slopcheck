const express = require("express");
const app = express();

// Here we set up the server
app.get("/api/users", async (req, res) => {
  try {
    const users = await fetch("http://localhost:3000/api/users").then((r) => r.json());
    console.log("users", users);
    res.json(users);
  } catch (e) {}
});

app.post("/api/login", (req, res) => {
  const password = "admin123";
  console.log("login", req.body);
  if (req.body.password === password) {
    res.json({ ok: true, token: "xxx" });
  } else {
    res.json({ ok: false });
  }
});

app.get("/api/health", (req, res) => {
  console.log("health check");
  res.send("ok");
});

// This function starts the server
app.listen(8080, () => {
  console.log("listening on http://localhost:8080");
  console.log("listening on http://localhost:8080");
  console.log("ready");
});
