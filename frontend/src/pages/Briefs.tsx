import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Sparkles } from "lucide-react";
import { useState } from "react";
import { EmptyState, PageHeader, Panel, SkeletonPage } from "../components/ui";
import { useI18n } from "../hooks/useI18n";
import { getJson, postJson, putJson } from "../services/http";

type Shot = {
  role: string;
  description: string;
  keyframe_prompt: string;
  motion_prompt: string;
  duration_seconds: number;
  on_screen_text: string;
  voiceover: string;
};
type Brief = {
  title: string;
  reference_rationale: string;
  scene: string;
  product_placement: string;
  selling_angle: string;
  target_audience: string;
  style: string[];
  colors: string[];
  shots?: Shot[];
  selected_reference_ids: string[];
};
type BriefRecord = { product_id: string; user_idea: string; brief: Brief; status: "draft" | "approved" };
type Product = { product_id: string; title: string | null; images: string[] };
type ReferenceImage = { image_id: string; image_url: string };

const API = "/api/v1/products";
const TEXT_FIELDS: { key: "scene" | "product_placement" | "selling_angle" | "target_audience"; label: string; rows: number }[] = [
  { key: "scene", label: "Scene", rows: 3 },
  { key: "product_placement", label: "Product placement", rows: 3 },
  { key: "selling_angle", label: "Selling angle", rows: 2 },
  { key: "target_audience", label: "Target audience", rows: 2 },
];
const SHOT_FIELDS: { key: "description" | "keyframe_prompt" | "motion_prompt" | "on_screen_text" | "voiceover"; label: string; rows: number }[] = [
  { key: "description", label: "What the viewer sees", rows: 2 },
  { key: "keyframe_prompt", label: "Keyframe image prompt", rows: 5 },
  { key: "motion_prompt", label: "Motion prompt", rows: 2 },
  { key: "on_screen_text", label: "Text on screen", rows: 1 },
  { key: "voiceover", label: "Voice-over", rows: 2 },
];
const words = (text: string) => text.split(",").map((word) => word.trim()).filter(Boolean);

export function BriefsPage() {
  const { t } = useI18n();
  const selections = useQuery({ queryKey: ["product-selections"], queryFn: ({ signal }) => getJson<Record<string, string | null>>(`${API}/selections`, signal) });
  const products = useQuery({ queryKey: ["products"], queryFn: ({ signal }) => getJson<Product[]>(API, signal) });
  const briefs = useQuery({ queryKey: ["briefs"], queryFn: ({ signal }) => getJson<BriefRecord[]>(`${API}/briefs`, signal) });
  const references = useQuery({
    queryKey: ["reference-images", "live"],
    queryFn: ({ signal }) => getJson<ReferenceImage[]>(`${API}/reference-images?status=live`, signal),
  });

  if (selections.isLoading || products.isLoading || briefs.isLoading) return <SkeletonPage />;
  const selectedIds = Object.keys(selections.data ?? {});
  const productById = new Map((products.data ?? []).map((product) => [product.product_id, product]));
  const briefById = new Map((briefs.data ?? []).map((record) => [record.product_id, record]));
  const imageById = new Map((references.data ?? []).map((image) => [image.image_id, image.image_url]));

  return (
    <>
      <PageHeader
        eyebrow="Affiliate content"
        title="Briefs"
        description="The agent writes one brief per selected product from its best live reference scenes. Add your own idea and the agent builds on it."
      />
      {selectedIds.length === 0 && (
        <EmptyState icon={<FileText />} title="No products selected" text="Select products for content on the Products page first." />
      )}
      {selectedIds.map((productId) => (
        <BriefCard
          key={productId}
          productId={productId}
          productType={selections.data?.[productId] ?? null}
          product={productById.get(productId)}
          record={briefById.get(productId)}
          imageById={imageById}
          t={t}
        />
      ))}
    </>
  );
}

function BriefCard({
  productId,
  productType,
  product,
  record,
  imageById,
  t,
}: {
  productId: string;
  productType: string | null;
  product: Product | undefined;
  record: BriefRecord | undefined;
  imageById: Map<string, string>;
  t: (key: string) => string;
}) {
  const client = useQueryClient();
  const [idea, setIdea] = useState(record?.user_idea ?? "");
  const refresh = () => client.invalidateQueries({ queryKey: ["briefs"] });
  const create = useMutation({
    mutationFn: () => postJson<BriefRecord>(`${API}/${productId}/brief`, { idea }),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: ({ brief, status }: { brief: Partial<Brief>; status: "draft" | "approved" }) =>
      putJson<BriefRecord>(`${API}/${productId}/brief`, { brief, status }),
    onSuccess: refresh,
  });

  return (
    <Panel>
      <div className="brief-head">
        {product?.images[0] && <img src={product.images[0]} alt="" width={56} height={56} />}
        <div>
          <strong>{product?.title ?? productId}</strong>
          <small>{productType ?? t("No product type yet. Regenerate keywords on the Products page.")}</small>
        </div>
        {record && <span className={`badge badge--${record.status === "approved" ? "success" : "warning"}`}>{record.status}</span>}
      </div>
      <label className="brief-field">
        <span>{t("Your idea (optional)")}</span>
        <textarea rows={2} value={idea} onChange={(event) => setIdea(event.target.value)} placeholder={t("e.g. sunny balcony, tidy feeling for small apartments")} />
      </label>
      <div className="brief-actions">
        <button className="primary-button" disabled={create.isPending || !productType} onClick={() => create.mutate()}>
          <Sparkles size={15} /> {create.isPending ? t("Writing…") : record ? t("Regenerate brief") : t("Create brief")}
        </button>
      </div>
      {create.error && <p role="alert">{create.error.message}</p>}
      {record && (
        <form
          key={`${record.product_id}-${record.status}-${record.brief.title}`}
          className="brief-form"
          onSubmit={(event) => {
            event.preventDefault();
            const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
            const data = new FormData(event.currentTarget);
            const brief: Partial<Brief> = {
              title: String(data.get("title")),
              style: words(String(data.get("style"))),
              colors: words(String(data.get("colors"))),
            };
            for (const field of TEXT_FIELDS) Object.assign(brief, { [field.key]: String(data.get(field.key)) });
            brief.shots = (record.brief.shots ?? []).map((shot, index) => {
              const next: Shot = { ...shot, duration_seconds: Number(data.get(`shot_${index}_duration`)) || shot.duration_seconds };
              for (const field of SHOT_FIELDS) next[field.key] = String(data.get(`shot_${index}_${field.key}`));
              return next;
            });
            save.mutate({ brief, status: submitter?.value === "approved" ? "approved" : "draft" });
          }}
        >
          <label className="brief-field">
            <span>{t("Title")}</span>
            <input name="title" defaultValue={record.brief.title} />
          </label>
          <div className="brief-references">
            {record.brief.selected_reference_ids.map((id) => imageById.get(id) && <img key={id} src={imageById.get(id)} alt="" width={72} height={96} referrerPolicy="no-referrer" />)}
            <p>{record.brief.reference_rationale}</p>
          </div>
          {TEXT_FIELDS.map((field) => (
            <label className="brief-field" key={field.key}>
              <span>{t(field.label)}</span>
              <textarea name={field.key} rows={field.rows} defaultValue={String(record.brief[field.key] ?? "")} />
            </label>
          ))}
          {(record.brief.shots ?? []).map((shot, index) => (
            <fieldset className="brief-shot" key={`${index}-${shot.keyframe_prompt}`}>
              <legend>{`${index + 1}. ${shot.role}`}</legend>
              <label className="brief-field">
                <span>{t("Seconds")}</span>
                <input name={`shot_${index}_duration`} type="number" min={1} max={15} defaultValue={shot.duration_seconds} />
              </label>
              {SHOT_FIELDS.map((field) => (
                <label className="brief-field" key={field.key}>
                  <span>{t(field.label)}</span>
                  <textarea name={`shot_${index}_${field.key}`} rows={field.rows} defaultValue={shot[field.key]} />
                </label>
              ))}
            </fieldset>
          ))}
          {!record.brief.shots?.length && <p>{t("This brief has no storyboard yet. Regenerate it.")}</p>}
          <label className="brief-field">
            <span>{t("Style (comma separated)")}</span>
            <input name="style" defaultValue={record.brief.style.join(", ")} />
          </label>
          <label className="brief-field">
            <span>{t("Colors (comma separated)")}</span>
            <input name="colors" defaultValue={record.brief.colors.join(", ")} />
          </label>
          <div className="brief-actions">
            <button className="secondary-button" type="submit" value="draft" disabled={save.isPending}>{t("Save draft")}</button>
            <button className="primary-button" type="submit" value="approved" disabled={save.isPending}>{t("Approve brief")}</button>
          </div>
          {save.error && <p role="alert">{save.error.message}</p>}
        </form>
      )}
    </Panel>
  );
}
