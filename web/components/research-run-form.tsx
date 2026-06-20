/**
 * @fileoverview Form component for launching a new research run.
 */

/** Props for the ResearchRunForm component. */
type ResearchRunFormProps = {
  /** Form submission handler. */
  action: (formData: FormData) => void | Promise<void>;
};

/**
 * Renders a form to start a research run with strategy, portfolio, and symbol
 * inputs.
 *
 * @param action Form submission handler.
 * @returns The research run form element.
 */
export function ResearchRunForm({ action }: ResearchRunFormProps) {
  return (
    <section className="panel" aria-labelledby="research-run-form-title">
      <div className="panel-heading">
        <h2 id="research-run-form-title">启动真实研究运行</h2>
        <span>POST /api/v1/research-runs</span>
      </div>
      <form action={action} className="action-form">
        <div className="form-grid">
          <label className="form-field">
            <span>策略 ID</span>
            <input name="strategy_id" defaultValue="default" required />
          </label>
          <label className="form-field">
            <span>策略版本</span>
            <input name="version_id" defaultValue="v0.1" required />
          </label>
          <label className="form-field">
            <span>组合 ID</span>
            <input name="portfolio_id" defaultValue="demo" />
          </label>
        </div>
        <label className="form-field">
          <span>标的代码</span>
          <textarea
            name="symbols"
            placeholder="000001.SZ, 600000.SH；为空时由后端按组合或默认 universe 决定"
            rows={3}
          />
        </label>
        <button className="primary-button" type="submit">
          启动研究运行
        </button>
      </form>
    </section>
  );
}
