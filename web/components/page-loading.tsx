/**
 * @fileoverview Skeleton loading placeholder for workspace pages.
 */

/** Props for the PageLoading component. */
type PageLoadingProps = {
  /** Main page heading. */
  title: string;
  /** Eyebrow text shown above the heading. */
  eyebrow: string;
};

/**
 * Renders a skeleton workspace layout while page data is loading.
 *
 * @param title Main page heading.
 * @param eyebrow Eyebrow text.
 * @returns The skeleton loading element.
 */
export function PageLoading({ title, eyebrow }: PageLoadingProps) {
  return (
    <main className="workspace-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
        <div className="status-strip">
          <span>正在连接后端</span>
          <span>实时数据</span>
        </div>
      </section>
      <section className="metric-grid" aria-label="加载中">
        {Array.from({ length: 4 }).map((_, index) => (
          <div className="metric-tile skeleton-tile" key={index}>
            <span className="skeleton-line short" />
            <strong className="skeleton-line" />
            <span className="skeleton-line tiny" />
          </div>
        ))}
      </section>
      <section className="workspace-grid">
        <div className="panel skeleton-panel" />
        <div className="panel skeleton-panel compact" />
      </section>
    </main>
  );
}
