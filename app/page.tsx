export default function HomePage() {
  return (
    <main style={{ fontFamily: 'Inter, Arial, sans-serif', padding: '2rem', lineHeight: 1.6 }}>
      <h1>VibeCoder Control Plane</h1>
      <p>Frontend is configured as a thin client for the FastAPI backend.</p>
      <ul>
        <li><code>POST /api/smp</code> - proxy SMP query calls to FastAPI <code>/smp/query</code></li>
        <li><code>POST /api/smp/init</code> - proxy workspace initialization to FastAPI <code>/workspace/init</code></li>
      </ul>
    </main>
  );
}
