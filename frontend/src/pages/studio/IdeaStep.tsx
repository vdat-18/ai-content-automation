import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, User } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../../components/ui";
import { useLightbox } from "../../hooks/useLightbox";
import { API, usePeople, useStartPipeline } from "../../hooks/useStudio";
import { runStopped } from "../../lib/studio";
import { deleteJson, postJson, putFile, putJson } from "../../services/http";
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
  const [picked, setPicked] = useState<string | null>(null);
  const start = useStartPipeline(productId);
  const startOver = useMutation({
    mutationFn: () => deleteJson(`${API}/${productId}/brief`),
    onSuccess: () => {
      for (const key of ["brief", "briefs", "keyframes", "clips", "video-info", "outputs", "pipeline"]) void client.invalidateQueries({ queryKey: [key] });
      setParams({});
    },
  });
  // every video follows one person of the library: the one picked, else the default
  const chosen = people.data?.find((p) => p.id === picked) ?? people.data?.find((p) => p.default) ?? people.data?.[0];
  const needsPhoto = people.isSuccess && !(chosen && chosen.photos > 0);

  const begin = () => {
    const prefix = styles.length ? `Style: ${styles.join(", ").toLowerCase()}. ` : "";
    start.mutate({ until: "script", idea: `${prefix}${idea}`.trim(), video_seconds: seconds, persona_id: chosen?.id });
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

          <PeoplePicker people={people.data ?? []} chosen={chosen} onPick={setPicked} />

          <section className="card pad stack" aria-labelledby="len">
            <h2 id="len">How long should the video be?</h2>
            <div className="row" role="group" aria-label="Video length">
              {Object.entries(LENGTHS).map(([key, { scenes, about }]) => {
                const n = Number(key);
                return <button key={n} type="button" className="chip" aria-pressed={seconds === n} onClick={() => setSeconds(n)}>{`${scenes} ${scenes === 1 ? "scene" : "scenes"}, about ${about} seconds`}</button>;
              })}
            </div>
            <p className="muted small">{`The script takes about a minute and you read it first. After you approve it, the images and the video take about ${MINUTES[seconds]} more minutes. You can leave the page.`}</p>
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
            <li>Writes the script in the voice of a young seller.</li>
            <li>Stops so you can read and fix the script.</li>
            <li>Creates each scene and checks it matches the real product.</li>
            <li>Stops so you can review the images.</li>
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

function PeoplePicker({ people, chosen, onPick }: { people: Persona[]; chosen: Persona | undefined; onPick: (id: string) => void }) {
  const client = useQueryClient();
  const lightbox = useLightbox();
  const [rights, setRights] = useState(false);
  const [name, setName] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["persona"] });
  const photos = chosen?.photos ?? 0;
  const create = useMutation({
    mutationFn: () => postJson<Persona>(`${API}/persona`, { name: name.trim() }),
    onSuccess: (person) => { setName(""); onPick(person.id); void refresh(); },
  });
  const upload = useMutation({
    // the first photo replaces the person's photos, the others join them
    mutationFn: async (files: File[]) => {
      for (const [index, file] of files.entries()) {
        await putFile(`${API}/persona/${chosen?.id}/image?rights=confirmed${index > 0 || photos > 0 ? "&add=true" : ""}`, file);
      }
    },
    onSuccess: refresh,
  });
  const makeDefault = useMutation({ mutationFn: () => putJson(`${API}/persona/${chosen?.id}/default`, {}), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => deleteJson(`${API}/persona/${chosen?.id}`), onSuccess: refresh });
  const sources = Array.from({ length: photos }, (_, index) => ({ src: `${API}/persona/${chosen?.id}/image?n=${index}&v=${chosen?.attempts}` }));
  return (
    <section className="card pad stack" aria-labelledby="who">
      <div>
        <h2 id="who">Who appears in the video?</h2>
        <p className="muted small">Every video follows one person, the same in all of them. The face in the images follows the photos; clothes and places change with each scene. A video keeps the person it was written for.</p>
      </div>
      <div className="row" role="group" aria-label="People">
        {people.map((person) => (
          <button key={person.id} type="button" className="chip" aria-pressed={chosen?.id === person.id} onClick={() => onPick(person.id)}>
            {person.name}{person.default ? " (default)" : ""}
          </button>
        ))}
      </div>
      <form className="row" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
        <input type="text" value={name} maxLength={60} placeholder="Add a person: name" aria-label="Name of a new person" onChange={(event) => setName(event.target.value)} />
        <button type="submit" className="btn" disabled={!name.trim() || create.isPending}>{create.isPending ? "Adding…" : "Add person"}</button>
      </form>
      {chosen && (
        <>
          <div className="slots">
            {sources.map((source, index) => (
              <div className="slot" key={source.src}><img src={source.src} alt={`${chosen.name}, photo ${index + 1}`} {...lightbox.zoom(sources, index)} /></div>
            ))}
            {photos === 0 && <div className="slot" aria-hidden="true"><User size={32} /></div>}
            <label className={`slot slot-add${rights ? "" : " disabled"}`} title={rights ? "Add photos" : "Confirm the permission below first"}>
              {upload.isPending ? <Spinner /> : <Plus size={22} aria-hidden="true" />}
              {upload.isPending ? "Uploading" : "Add photos"}
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={!rights || upload.isPending} onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) upload.mutate(files); event.target.value = ""; }} />
            </label>
          </div>
          <label className="check">
            <input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} />
            I have the right to use this person's image in ads.
          </label>
          <div className="row">
            {!chosen.default && <button type="button" className="link" disabled={makeDefault.isPending} onClick={() => makeDefault.mutate()}>Make {chosen.name} the default</button>}
            <button type="button" className="link link-danger" disabled={remove.isPending} onClick={() => { if (window.confirm(`Remove ${chosen.name} and the photos? Videos written for this person lose them.`)) remove.mutate(); }}>Remove {chosen.name}</button>
          </div>
        </>
      )}
      <ErrorNote error={create.error ?? upload.error ?? makeDefault.error ?? remove.error} />
      {lightbox.node}
    </section>
  );
}
