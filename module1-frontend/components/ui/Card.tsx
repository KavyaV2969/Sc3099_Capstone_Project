export function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="page-centered">
      <div className="card-panel">
        {children}
      </div>
    </div>
  );
}