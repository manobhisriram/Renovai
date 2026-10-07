import { useEffect, useState } from "react";
import { api } from "../services/api";

/** Images are served behind authentication, so they are fetched with the bearer token and shown via a blob URL. */
export function AuthImage({ path, alt, className = "thumb" }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    api.blobUrl(path).then((u) => { if (cancelled) URL.revokeObjectURL(u); else { url = u; setSrc(u); } }).catch(() => setFailed(true));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [path]);
  if (failed) return <div className={className} role="img" aria-label={`${alt} (could not be loaded)`} />;
  return src ? <img className={className} src={src} alt={alt} /> : <div className={className} aria-busy />;
}
