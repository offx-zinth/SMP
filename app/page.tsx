export default function HomePage() {
  return (
    <main style={{ fontFamily: 'Inter, Arial, sans-serif', padding: '2rem', lineHeight: 1.6 }}>
      <h1>Structural Memory Protocol (SMP)</h1>
      <p>
        SMP is running. Use the API endpoints to index files and issue JSON-RPC queries.
      </p>
      <ul>
        <li><code>GET /api/smp/init</code> - load sample files into memory</li>
        <li><code>POST /api/smp</code> - send JSON-RPC requests</li>
      </ul>
    </main>
  );
}
