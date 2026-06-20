/**
 * @fileoverview Form component for submitting feedback on a research item.
 */

/** Props for the ResearchFeedbackForm component. */
type ResearchFeedbackFormProps = {
  /** Form submission handler. */
  action: (formData: FormData) => void | Promise<void>;
};

/**
 * Renders a research feedback form with type and comment fields.
 *
 * @param action Form submission handler.
 * @returns The feedback form element.
 */
export function ResearchFeedbackForm({ action }: ResearchFeedbackFormProps) {
  return (
    <section className="panel" aria-labelledby="feedback-title">
      <div className="panel-heading">
        <h2 id="feedback-title">研究反馈</h2>
        <span>POST /feedback</span>
      </div>
      <form action={action} className="action-form">
        <label className="form-field">
          <span>反馈类型</span>
          <select name="feedback_type" defaultValue="comment">
            <option value="accept">采纳</option>
            <option value="reject">拒绝</option>
            <option value="watch">加入观察</option>
            <option value="comment">备注</option>
          </select>
        </label>
        <label className="form-field">
          <span>反馈说明</span>
          <textarea
            name="comment"
            placeholder="写入真实 feedback 记录，用于后续审计和策略改进"
            rows={3}
          />
        </label>
        <button className="primary-button" type="submit">
          提交研究反馈
        </button>
      </form>
    </section>
  );
}
