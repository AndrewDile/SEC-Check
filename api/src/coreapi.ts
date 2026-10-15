import express from 'express';

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// Contract v1.0.0 operations (all POST). Stubs until wired to src/db.
const notImplemented: express.RequestHandler = (_req, res) => {
  res.status(501).json({ Error: 'NOT_IMPLEMENTED', Message: 'Not implemented yet' });
};

app.post('/incidents', notImplemented);
app.post('/tickets', notImplemented);
app.post('/notifier', notImplemented);
app.post('/logs', notImplemented);
app.post('/dependencies', notImplemented);
app.post('/reset', notImplemented);

const port = Number(process.env.PORT ?? 3001);
app.listen(port, () => console.log(`Core API listening on :${port}`));
