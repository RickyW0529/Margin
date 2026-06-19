import type { ProviderStatus } from "@/lib/api";

type ProviderStatusPanelProps = {
  providers: ProviderStatus[];
  title?: string;
};

export function ProviderStatusPanel({
  providers,
  title = "Provider 状态",
}: ProviderStatusPanelProps) {
  return (
    <section className="panel" aria-labelledby="provider-status-title">
      <div className="panel-heading">
        <h2 id="provider-status-title">{title}</h2>
        <span>{providers.length} providers</span>
      </div>
      {providers.length === 0 ? (
        <div className="empty-state compact">暂无 Provider 状态</div>
      ) : (
        <ul className="provider-list">
          {providers.map((provider) => (
            <li key={provider.provider}>
              <div>
                <strong>{provider.provider}</strong>
                <span>{provider.message}</span>
              </div>
              <span className={`badge provider-${provider.status.toLowerCase()}`}>
                {provider.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
