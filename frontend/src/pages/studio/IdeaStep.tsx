import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, User } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../../components/ui";
import { useLightbox } from "../../hooks/useLightbox";
import { API, usePeople, useStartPipeline } from "../../hooks/useStudio";
import { runStopped } from "../../lib/studio";
import { deleteJson, postJson, putFile } from "../../services/http";
import type { BriefRecord, Persona, PipelineRun, Product } from "../../types/studio";

// Every scene is filmed for 15 seconds but plays about 13 in the video, so the length is not exact
const LENGTHS: Record<number, { scenes: number; about: number }> = { 15: { scenes: 1, about: 13 }, 30: { scenes: 2, about: 27 }, 45: { scenes: 3, about: 40 }, 60: { scenes: 4, about: 54 } };
const MINUTES: Record<number, number> = { 15: 5, 30: 8, 45: 11, 60: 14 };
const STYLES = ["Natural, everyday", "Honest review", "Before and after", "Quick how-to"];

export function IdeaStep({ productId, product, productType, record, run }: { productId: string; product: Product; productType: string | null; record: BriefRecord | null; run: PipelineRun | undefined }) {
  const [, setParams] = useSearchParams();
  const [seconds, setSeconds] = useState(30);
  const [styles, setStyles] = useState<string[]>([STYLES[0]]);
  const [idea, setIdea] = useState(record?.user_idea ?? "");
  const client = useQueryClient();
  const people = usePeople();
  const start = useStartPipeline(productId);
  const startOver = useMutation({
    mutationFn: () => deleteJson(`${API}/${productId}/brief`),
    onSuccess: () => {
      for (const key of ["brief", "briefs", "keyframes", "clips", "video-info", "outputs", "pipeline"]) void client.invalidateQueries({ queryKey: [key] });
      setParams({});
    },
  });
  // every video follows the default person of the library; the user only sees "your photos"
  const chosen = people.data?.find((p) => p.default) ?? people.data?.[0];
  const needsPhoto = people.isSuccess && !(chosen && chosen.photos > 0);

  const begin = () => {
    const prefix = styles.length ? `Style: ${styles.join(", ").toLowerCase()}. ` : "";
    start.mutate({ until: "images", idea: `${prefix}${idea}`.trim(), video_seconds: seconds, persona_id: chosen?.id });
  };

  return (
    <>
      <header className="page-head"><div><h1>How should your video look?</h1><p>Fill in the basics, the AI does the rest. You can change things in the next steps.</p></div></header>
      {run && runStopped(run) && (
        <div className="notice notice-warn" role="alert"><div>The last run stopped. {run.message}</div></div>
      )}
      <div className="studio-cols">
        <div className="studio-main">
          <section className="card pad product-line" aria-label="Product">
            <div className="icon">{product.images[0] ? <img src={product.images[0]} alt="" referrerPolicy="no-referrer" /> : null}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h2 style={{ fontSize: 17 }}>{product.title}</h2>
              <span className="muted small">{product.seller?.name}</span>
            </div>
          </section>

          <PersonPhotos chosen={chosen} />

          <section className="card pad stack" aria-labelledby="len">
            <h2 id="len">How long should the video be?</h2>
            <div className="row" role="group" aria-label="Video length">
              {Object.entries(LENGTHS).map(([key, { scenes, about }]) => {
                const n = Number(key);
                return <button key={n} type="button" className="chip" aria-pressed={seconds === n} onClick={() => setSeconds(n)}>{`${scenes} ${scenes === 1 ? "scene" : "scenes"}, about ${about} seconds`}</button>;
              })}
            </div>
            <p className="muted small">{`The script and the first image take a few minutes. You approve the images before the video is made. After you approve them, the video takes about ${MINUTES[seconds]} more minutes. You can leave the page.`}</p>
          </section>

          <section className="card pad stack" aria-labelledby="idea">
            <h2 id="idea">Style and idea <span className="muted" style={{ fontWeight: 400, fontSize: 15 }}>(optional)</span></h2>
            <div className="row" role="group" aria-label="Style">
              {STYLES.map((s) => (
                <button key={s} type="button" className="chip" aria-pressed={styles.includes(s)} onClick={() => setStyles(styles.includes(s) ? styles.filter((x) => x !== s) : [...styles, s])}>{s}</button>
              ))}
            </div>
            <label className="field">
              Anything else?
              <textarea rows={3} value={idea} onChange={(event) => setIdea(event.target.value)} placeholder="For example: a small rented room, window light, a friendly feeling" />
            </label>
          </section>
        </div>

        <aside className="studio-side card pad" aria-label="Summary">
          <h2>What the AI does next</h2>
          <ol className="muted" style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 8 }}>
            <li>Writes the script in the voice of a young seller and picks a reference photo for each scene.</li>
            <li>Creates the first scene and stops so you can look at it.</li>
            <li>After you approve it, creates the other scenes to match it. You approve each one.</li>
            <li>Then makes the video, voice-over and caption.</li>
          </ol>
          {record ? (
            <>
              <div className="notice"><div>This video is already in progress.</div></div>
              <button className="btn btn-primary btn-lg btn-block" onClick={() => setParams({})}>Continue where you left off</button>
              <button
                className="btn btn-block"
                disabled={startOver.isPending}
                onClick={() => {
                  if (window.confirm("This removes the script, the images, the clips and the video of this product. The product and the person photos stay. Continue?")) startOver.mutate();
                }}
              >
                {startOver.isPending ? "Removing…" : "Write a new script"}
              </button>
              <ErrorNote error={startOver.error} />
            </>
          ) : (
            <button className="btn btn-primary btn-lg btn-block" disabled={start.isPending || !productType || needsPhoto} onClick={begin}>
              {start.isPending ? <><Spinner />Starting…</> : needsPhoto ? "Add the person's photo first" : productType ? "Start making my video" : "Getting your product ready…"}
            </button>
          )}
          <ErrorNote error={start.error} />
        </aside>
      </div>
    </>
  );
}

const MAX_PHOTOS = 3; // only this many photos of the person reach the image model

function PersonPhotos({ chosen }: { chosen: Persona | undefined }) {
  const client = useQueryClient();
  const lightbox = useLightbox();
  const refresh = () => client.invalidateQueries({ queryKey: ["persona"] });
  const photos = chosen?.photos ?? 0;
  const upload = useMutation({
    // the first person is created on the first upload; "replace" starts the photos over
    mutationFn: async ({ files, replace }: { files: File[]; replace: boolean }) => {
      const person = chosen ?? (await postJson<Persona>(`${API}/persona`, { name: "Me" }));
      const room = replace ? MAX_PHOTOS : MAX_PHOTOS - photos;
      for (const [index, file] of files.slice(0, room).entries()) {
        const add = replace ? index > 0 : index > 0 || photos > 0;
        await putFile(`${API}/persona/${person.id}/image?rights=confirmed${add ? "&add=true" : ""}`, file);
      }
    },
    onSuccess: refresh,
  });
  const sources = Array.from({ length: photos }, (_, index) => ({ src: `${API}/persona/${chosen?.id}/image?n=${index}&v=${chosen?.attempts}` }));
  const pick = (replace: boolean) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length) upload.mutate({ files, replace });
    event.target.value = "";
  };
  return (
    <section className="card pad stack" aria-labelledby="who">
      <div>
        <h2 id="who">Who appears in the video?</h2>
        <p className="muted small">{`Upload 1 to ${MAX_PHOTOS} clear photos of the person's face. The same person appears in every scene; clothes and places change.`}</p>
      </div>
      <div className="slots">
        {sources.map((source, index) => (
          <div className="slot" key={source.src}><img src={source.src} alt={`Photo ${index + 1}`} {...lightbox.zoom(sources, index)} /></div>
        ))}
        {photos === 0 && <div className="slot" aria-hidden="true"><User size={32} /></div>}
        {photos < MAX_PHOTOS && (
          <label className="slot slot-add">
            {upload.isPending ? <Spinner /> : <Plus size={22} aria-hidden="true" />}
            {upload.isPending ? "Uploading" : "Add photos"}
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={upload.isPending} onChange={pick(false)} />
          </label>
        )}
      </div>
      {photos > 0 && (
        <label className="link">
          Replace the photos
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden disabled={upload.isPending} onChange={pick(true)} />
        </label>
      )}
      <ErrorNote error={upload.error} />
      {lightbox.node}
    </section>
  );
}
