/**
 * @fileoverview Form component for submitting feedback on a research item.
 */

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

type ResearchFeedbackFormProps = {
  action: (formData: FormData) => void | Promise<void>;
};

/** Renders a research feedback form with type and comment fields. */
export function ResearchFeedbackForm({ action }: ResearchFeedbackFormProps) {
  return (
    <Card aria-labelledby="feedback-title">
      <CardHeader>
        <CardTitle id="feedback-title">研究反馈</CardTitle>
        <span className="text-xs text-muted-foreground">POST /feedback</span>
      </CardHeader>
      <CardContent>
        <form action={action} className="grid gap-3">
          <div className="grid gap-1.5">
            <Label>反馈类型</Label>
            <Select name="feedback_type" defaultValue="comment">
              <option value="accept">采纳</option>
              <option value="reject">拒绝</option>
              <option value="watch">加入观察</option>
              <option value="comment">备注</option>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>反馈说明</Label>
            <Textarea
              name="comment"
              placeholder="写入真实 feedback 记录，用于后续审计和策略改进"
              rows={3}
            />
          </div>
          <Button type="submit">提交研究反馈</Button>
        </form>
      </CardContent>
    </Card>
  );
}
