# Design: the reference image library and a plan for many contents per product

Status: phase 1 (automatic image library) and phase 2 (duplicate detection by embedding) are done;
phase 3 is still a proposal. Phase 2 uses DINOv3 ViT-S/16 running on ONNX on the CPU (changeable with
`AIC_EMBEDDING_MODEL`); two images count as duplicates by embedding similarity (`AIC_DUPLICATE_SIMILARITY`,
default 0.80) or a dHash distance of at most 4 bits, tuned on real data. Goal: one product yields
several **clearly different** ads from a library that can reach thousands of reference images, without
a person reviewing each image.

## 1. Problems of the first version

| Point | Then | Consequence for a large library |
|---|---|---|
| Review | A person approves each image after the screening model | Not workable with hundreds of images |
| Picking images for a brief | The 8 most recently approved images | Not the best, not fitting the product, not diverse |
| Number of contents | One brief per product | Many ads mean clicking again, and the briefs tend to look alike |
| Duplicate detection | By URL only | The same image repinned under another link still gets in and costs a screening call |
| Image quality | Pass or fail only | Cannot rank |

## 2. Design principles

1. **The screening model is the only gate.** An image that passes is live automatically; the user only
   **deletes** images in the dashboard. Deleted images are remembered so the next crawl does not load
   them again.
2. **Cheap first, expensive later.** Duplicate detection by embedding runs before the screening call so
   no money is spent on look-alike images.
3. **Choose images with maths, write briefs with the LLM.** Choosing reference images (relevant,
   diverse, unused) is an algorithm over embeddings; the LLM only sees a small chosen group.
4. **Plan first, write after.** For N contents of one product, a planning step makes sure the N differ
   in selling angle, audience and setting before each brief is written.

## 3. Embedding: which kind

Recommendation: a **locally run CLIP-style model** (image and text in one vector space, no key, no
rate limits).

| Option | Pros | Cons |
|---|---|---|
| A. Local CLIP (`fastembed`, ONNX, CPU) | Free, fast, image and text share a space so images can be found by idea; no network | One more library and a model of a few hundred MB in the Docker image; weak with Vietnamese text, so ideas need translating to English first |
| B. Multimodal embedding API | No image weight, understands Vietnamese better | Costs money, may hit rate limits, the endpoint must exist |
| C. Embed the text description written by the screening model | Works with any OpenAI-compatible endpoint | Cannot catch visually duplicated images; loses visual information |

Embeddings serve three jobs:
1. **Duplicate detection:** a new image whose cosine similarity to an existing one passes the threshold
   is dropped before the screening call.
2. **Relevance:** rank images by closeness to the user's idea and the product description.
3. **Diversity:** avoid choosing many near-identical images for different contents.

Storage: for a few thousand images per type, an array of numbers in a column with cosine computed in
Python is enough. Move to `pgvector` only when the library is much larger (it needs another Postgres
image, so not now).

## 4. The crawl → library flow

```
crawl Pinterest
  → drop duplicate links (done)
  → embed; drop images close to an existing or a deleted image
  → screening model: pass/fail + a description (setting, light, style, colours, where the product fits)
  → pass: live (shown in the dashboard); fail: rejected (hidden, still remembered to avoid rescoring)
```

Dashboard: the Approve/Reject buttons are gone; only **Delete** (soft delete) remains. There is no
quality score; when choosing images for a brief the system takes the most different images by
embedding vector.

## 5. From one product to N contents

Input: the product, N (how many contents), and the user's ideas (optional, possibly several).

1. **Narrow the candidates.** From the library of the product type, take about 3N images by a combined
   score:
   `score = a·relevance(idea, product) + b·quality − c·already used for this product`
   then pick one by one in **MMR** style (each chosen image lowers the score of its neighbours) so the
   candidates are already diverse.
2. **Plan (one LLM call, text only).** It receives the product data, the user's ideas and a short
   description of each candidate, and returns N plans: selling angle, audience, hook, main and
   secondary image, how the setting varies. Constraint: no two plans share a selling angle or a main
   image.
3. **Write the briefs (N parallel calls).** Each plan becomes a full brief; this time the LLM sees the
   real product photos (it picks at most 5 for image generation) and reads the text description of the
   reference images to choose exactly one setting.
4. **Record usage.** Which reference image was used for which product is stored, so later runs prefer
   unused images. Reuse across different products is fine.

User ideas: with several ideas, each anchors one plan; with fewer than N, the agent picks the
direction of the rest but keeps them different from the existing ideas.

## 6. Data changes

- `product_briefs`: the primary key changes from `product_id` to `brief_id`; add `product_id`,
  `batch_id`, `plan` (JSON) and `status`.
- `reference_uses(product_id, image_id, brief_id)`.
- `reference_images`: add `embedding`, `quality_score`, `removed_at`; drop the `approved` status.
- Dashboard: the Briefs page lets the user enter N, press "Create N contents" and see the briefs of
  a product.

## 7. Suggested order

| Phase | Content | Depends on |
|---|---|---|
| 1. Automatic library | Images that pass screening are live; delete only; quality score; dashboard sorted by score | Nothing |
| 2. Embedding | Embed images, detect duplicates before screening, store vectors | Choice of option A/B/C |
| 3. Plan for many contents | MMR narrowing, planning, N briefs, usage record, UI | Phases 1 and 2 |

Each phase is usable on its own. Phase 1 is the smallest and removes manual review at once.

## 8. Risks and mitigations

- **The screening model lets junk into the library** once no one reviews: a minimum quality threshold,
  quick deletion in the UI, and the rejected set stays viewable so the prompt can be tuned.
- **A wrong duplicate threshold:** tune on real data; also keep images dropped as duplicates so they
  can be checked again.
- **Pinterest image copyright:** images are used only as setting references; a brief must not copy an
  image, logo or text as is (this is already in the prompt).
- **LLM cost multiplies with N:** plan once, send only the images of the plan to the writing step, and
  cap N in the UI.
