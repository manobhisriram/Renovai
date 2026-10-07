"""Repository consistency checks that do not need Docker or Terraform installed.

Checks: Dockerfile COPY sources exist in their build context; compose wiring; CI workflow references;
Terraform syntax + reference/variable consistency; .gitignore coverage; no secrets in tracked files.
Run: python scripts/verify_repo.py   (needs pyyaml; python-hcl2 is optional but recommended)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
notes: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def tracked_files() -> list[Path]:
    skip = {"node_modules", ".venv", "venv", "dist", "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "qdrant_data", "uploads"}
    return [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & skip) and p.name != ".env"]


# ---------------------------------------------------------------------------------------------- Dockerfiles
def check_dockerfiles() -> None:
    for df, ctx in ((ROOT / "backend" / "Dockerfile", ROOT / "backend"), (ROOT / "frontend" / "Dockerfile", ROOT / "frontend")):
        if not df.exists():
            err(f"{df.relative_to(ROOT)} is missing")
            continue
        for n, line in enumerate(df.read_text().splitlines(), 1):
            m = re.match(r"\s*COPY\s+(.*)", line)
            if not m or "--from=" in line:
                continue
            parts = [p for p in m.group(1).split() if not p.startswith("--")]
            for src in parts[:-1]:
                if ".." in Path(src).parts:
                    err(f"{df.name}:{n} COPY source '{src}' escapes the build context")
                elif not any(ctx.glob(src)) and not (ctx / src).exists():
                    err(f"{df.relative_to(ROOT)}:{n} COPY source '{src}' not found in {ctx.relative_to(ROOT)}/")
        text = df.read_text()
        if "USER " not in text:
            err(f"{df.relative_to(ROOT)} never switches to a non-root USER")
        if "HEALTHCHECK" not in text:
            err(f"{df.relative_to(ROOT)} has no HEALTHCHECK")
    entry = ROOT / "backend" / "docker-entrypoint.sh"
    if not entry.exists() or not entry.stat().st_mode & 0o111:
        err("backend/docker-entrypoint.sh missing or not executable")
    tmpl = ROOT / "frontend" / "nginx.conf.template"
    if "${BACKEND_UPSTREAM}" not in tmpl.read_text():
        err("nginx.conf.template does not use ${BACKEND_UPSTREAM}")
    # entrypoint/CMD reference real modules
    if not (ROOT / "backend" / "app" / "main.py").exists() or "def app_factory" not in (ROOT / "backend" / "app" / "main.py").read_text():
        err("Dockerfile CMD references app.main:app_factory which does not exist")


# ---------------------------------------------------------------------------------------------- compose
def check_compose() -> None:
    import yaml

    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        path = ROOT / name
        if not path.exists():
            err(f"{name} missing")
            continue
        doc = yaml.safe_load(path.read_text().replace("!reset []", "[]"))
        services = doc.get("services", {})
        if name == "docker-compose.yml":
            for must in ("postgres", "redis", "qdrant", "backend", "frontend"):
                if must not in services:
                    err(f"{name}: service '{must}' missing")
            for svc, cfg in services.items():
                for dep in (cfg.get("depends_on") or {}):
                    if dep not in services:
                        err(f"{name}: {svc} depends_on unknown service {dep}")
                build = cfg.get("build")
                if build:
                    ctx = ROOT / (build if isinstance(build, str) else build["context"])
                    if not (ctx / "Dockerfile").exists():
                        err(f"{name}: {svc} build context {ctx} has no Dockerfile")
                for net in cfg.get("networks", []):
                    if net not in doc.get("networks", {}):
                        err(f"{name}: {svc} uses undefined network {net}")
                for vol in cfg.get("volumes", []):
                    vname = str(vol).split(":")[0]
                    if "/" not in vname and "." not in vname and vname not in doc.get("volumes", {}):
                        err(f"{name}: {svc} uses undefined volume {vname}")
            for svc in ("postgres", "redis", "qdrant"):
                if services[svc].get("ports"):
                    err(f"{name}: {svc} must not publish ports to the host")
                if "internal" not in services[svc].get("networks", []) or "edge" in services[svc].get("networks", []):
                    err(f"{name}: {svc} must be on the internal network only")
        else:
            for svc in services:
                if svc not in yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]:
                    err(f"{name}: overrides unknown service {svc}")


# ---------------------------------------------------------------------------------------------- workflows
def check_workflows() -> None:
    import yaml

    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        doc = yaml.safe_load(wf.read_text())
        if not doc.get("jobs"):
            err(f"{wf.name}: no jobs")
        text = wf.read_text()
        for m in re.finditer(r"(?:working-directory|context|cache-dependency-path):\s*\.?/?([\w./-]+)", text):
            target = m.group(1)
            if not (ROOT / target).exists():
                err(f"{wf.name}: references missing path '{target}'")
        for job, cfg in doc["jobs"].items():
            for need in (cfg.get("needs") or []):
                if need not in doc["jobs"]:
                    err(f"{wf.name}: job {job} needs unknown job {need}")
        for script in re.findall(r"python (scripts/[\w./]+)", text):
            if not (ROOT / script).exists():
                err(f"{wf.name}: runs missing script {script}")


# ---------------------------------------------------------------------------------------------- terraform
def check_terraform() -> None:
    tf_dir = ROOT / "infra" / "terraform"
    files = sorted(tf_dir.glob("*.tf"))
    if not files:
        err("no Terraform files")
        return
    text = "\n".join(f.read_text() for f in files)
    try:
        import hcl2

        for f in files:
            hcl2.load(f.open())
    except ImportError:
        notes.append("python-hcl2 not installed: Terraform syntax parse skipped")
    except Exception as exc:
        err(f"Terraform HCL parse error: {str(exc)[:200]}")
    # Terraform itself forbids several attributes in a one-line block (python-hcl2 is more lenient).
    for f in files:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            m = re.match(r'^\s*[a-z_]+(?:\s+"[^"]+")*\s*\{(.*)\}\s*$', line)
            if m:
                inner = re.sub(r'"[^"]*"', '""', m.group(1))
                if inner.count("=") > 1 and "{" not in inner:
                    err(f"{f.name}:{n} single-line block with several attributes is invalid Terraform")
    declared_vars = set(re.findall(r'^variable\s+"([^"]+)"', text, re.M))
    used_vars = set(re.findall(r"\bvar\.([a-z_0-9]+)", text))
    for v in used_vars - declared_vars:
        err(f"Terraform: var.{v} used but not declared")
    for v in declared_vars - used_vars:
        err(f"Terraform: variable '{v}' declared but never used")
    resources = set(re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"', text, re.M))
    defined = {f"{t}.{n}" for t, n in resources}
    datas = {f"data.{t}.{n}" for t, n in re.findall(r'^data\s+"([^"]+)"\s+"([^"]+)"', text, re.M)}
    stripped = re.sub(r'"[^"\n]*"', lambda m: m.group(0) if "${" in m.group(0) else '""', text)
    for ref in set(re.findall(r"(?<![\w.\"/-])((?:aws|random)_[a-z0-9_]+\.[a-z_0-9]+)\b", stripped)):
        if ref not in defined:
            err(f"Terraform: reference to undefined resource {ref}")
    for ref in set(re.findall(r"\b(data\.[a-z_0-9]+\.[a-z_0-9]+)\b", text)):
        if ref not in datas:
            err(f"Terraform: reference to undefined data source {ref}")
    for out in re.findall(r"^output\s+\"([^\"]+)\"", text, re.M):
        notes.append(f"terraform output: {out}") if False else None
    if "publicly_accessible        = false" not in text:
        err("Terraform: RDS must not be publicly accessible")
    for bad in ('cidr_blocks = ["0.0.0.0/0"]',):
        for m in re.finditer(r'resource "aws_security_group" "(\w+)" \{(.*?)\n\}\n', text, re.S):
            name, body = m.groups()
            for ing in re.findall(r"ingress \{(.*?)\n  \}", body, re.S):
                if bad in ing and name != "alb":
                    err(f"Terraform: security group '{name}' allows ingress from the internet")
    for internal in ("db", "redis"):
        body = re.search(rf'resource "aws_security_group" "{internal}" \{{(.*?)\n\}}\n', text, re.S)
        if body and "cidr_blocks" in body.group(1):
            err(f"Terraform: {internal} security group must reference the backend SG, not CIDRs")


# ---------------------------------------------------------------------------------------------- git hygiene
def check_hygiene() -> None:
    gi = (ROOT / ".gitignore").read_text()
    for needed in (".env", "node_modules/", "__pycache__/", "*.db", ".venv/", "*.tfstate"):
        if needed not in gi:
            err(f".gitignore does not cover {needed}")
    if not (ROOT / ".env.example").exists():
        err(".env.example missing")
    patterns = [r"sk-ant-[A-Za-z0-9_\-]{20,}", r"AKIA[0-9A-Z]{16}", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", r"xox[bp]-[0-9A-Za-z-]{20,}",
                r"ghp_[A-Za-z0-9]{30,}", r"pat-[a-z]{2,3}\d-[0-9a-f-]{30,}"]
    for p in tracked_files():
        if p.suffix in {".png", ".jpg", ".woff2", ".lock", ".json"} and p.name != ".env.example" and p.stat().st_size > 400_000:
            continue
        try:
            body = p.read_text(errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            if re.search(pat, body):
                err(f"possible secret ({pat[:14]}...) in {p.relative_to(ROOT)}")
    for must in ("LICENSE", "README.md", "docs/architecture.md", "docs/deployment.md", "docs/security.md", "docs/testing.md", "docs/llmops.md", "docs/rag.md",
                 "docs/ai-architecture.md", "docs/api.md"):
        if not (ROOT / must).exists():
            err(f"required file missing: {must}")


def main() -> int:
    for fn in (check_dockerfiles, check_compose, check_workflows, check_terraform, check_hygiene):
        try:
            fn()
        except Exception as exc:  # a crashing check is a failing check
            err(f"{fn.__name__} crashed: {type(exc).__name__}: {exc}")
    for n in notes:
        print("note:", n)
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print(" -", e)
        return 1
    print("repo checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
