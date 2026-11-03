export type WorkspaceNotification = {
  notification_id: string;
  scope_type: string;
  scope_id: string;
  kind: string;
  title: string;
  detail: string;
  action_path: string | null;
  read_at: string | null;
  created_at: string;
  updated_at: string;
  payload: Record<string, unknown> | null;
};

export type WorkspaceNotificationList = {
  items: WorkspaceNotification[];
  total: number;
  unread: number;
};

export type CreativeKnowledgeStatus =
  | "draft"
  | "proposed"
  | "approved"
  | "rejected"
  | "expired"
  | "conflict";

export type CreativeKnowledgeType =
  | "fact"
  | "hard_rule"
  | "team_default"
  | "practice"
  | "hypothesis"
  | "lesson"
  | "qa_check"
  | "decision"
  | "feedback";

export type CreativeKnowledgeAuthority =
  | "owner"
  | "admin"
  | "lead"
  | "team"
  | "individual"
  | "external";

export type CreativeKnowledgeStage =
  | "persona"
  | "preparation"
  | "orchestration"
  | "review"
  | "revision"
  | "learning"
  | "performance";

export type CreativeKnowledgeScope = {
  niche_id: string | null;
  brand_id: string | null;
  product_archetype: string | null;
  product_family_id: string | null;
  variant_id: string | null;
  platform: string | null;
  market: string | null;
  asset_type: string | null;
  task_type: string | null;
};

export type CreativeKnowledge = {
  knowledge_id: string;
  knowledge_type: CreativeKnowledgeType;
  title: string;
  content: string;
  scope: CreativeKnowledgeScope;
  status: CreativeKnowledgeStatus;
  authority: CreativeKnowledgeAuthority;
  source_refs: string[];
  evidence_refs: string[];
  applies_to: CreativeKnowledgeStage[];
  contributor: string | null;
  non_conclusions: string[];
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};

export type CreativeKnowledgeList = {
  items: CreativeKnowledge[];
  total: number;
};

export type CreativeKnowledgeBootstrapResult = {
  bootstrap_id: string;
  checksum: string;
  applied: boolean;
  items: CreativeKnowledge[];
  total: number;
};

export type CreativeKnowledgeProposalRequest = {
  knowledge_id?: string;
  knowledge_type: CreativeKnowledgeType;
  title: string;
  content: string;
  scope: Partial<CreativeKnowledgeScope>;
  authority: CreativeKnowledgeAuthority;
  source_refs: string[];
  evidence_refs: string[];
  applies_to: CreativeKnowledgeStage[];
  contributor?: string;
  non_conclusions: string[];
};
