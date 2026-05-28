"""
GitConnector — detects project type and CI/CD pipelines from a Git repository
using the hosting provider's HTTP API (no local git installation required).

Supports:
  GitHub   — https://github.com/org/repo  or  git@github.com:org/repo.git
  GitLab   — https://gitlab.com/org/repo
  Bitbucket— https://bitbucket.org/org/repo  (file listing only)

Detection output (ProjectTypeInfo):
  project_type  — spring_boot_jar | spring_boot_war | jsp_war | maven_jar
                  gradle_jar | react | angular | vue | nextjs | nodejs | unknown
  build_tool    — maven | gradle | npm | yarn | unknown
  build_command — ready-to-run command on the remote server
  artifact_path — relative path to the built artifact
  deploy_method — jar_service | war_tomcat | static_web | node_server | unknown
  cicd_type     — github_actions | jenkins | gitlab_ci | circleci | bitbucket | none
  cicd_files    — detected CI/CD config file paths
  confidence    — high | medium | low
"""
import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── Result types ───────────────────────────────────────────────────────────

@dataclass
class ProjectTypeInfo:
    project_type: str
    build_tool: str
    build_command: str
    artifact_path: str
    deploy_method: str
    cicd_type: str
    cicd_files: list[str]
    detected_from: list[str]
    confidence: str           # "high" | "medium" | "low"

    @property
    def type_label(self) -> str:
        return _TYPE_LABELS.get(self.project_type, self.project_type)

    @property
    def type_icon(self) -> str:
        return _TYPE_ICONS.get(self.project_type, "📦")

    @property
    def cicd_label(self) -> str:
        return _CICD_LABELS.get(self.cicd_type, self.cicd_type)


_TYPE_LABELS = {
    "spring_boot_jar": "Spring Boot (JAR)",
    "spring_boot_war": "Spring Boot (WAR)",
    "jsp_war":         "JSP / Servlet (WAR)",
    "maven_jar":       "Maven JAR",
    "gradle_jar":      "Gradle JAR",
    "react":           "React",
    "angular":         "Angular",
    "vue":             "Vue.js",
    "nextjs":          "Next.js",
    "nodejs":          "Node.js",
    "unknown":         "Unknown",
}

_TYPE_ICONS = {
    "spring_boot_jar": "☕",
    "spring_boot_war": "☕",
    "jsp_war":         "☕",
    "maven_jar":       "📦",
    "gradle_jar":      "📦",
    "react":           "⚛️",
    "angular":         "🅰️",
    "vue":             "💚",
    "nextjs":          "▲",
    "nodejs":          "🟩",
    "unknown":         "❓",
}

_CICD_LABELS = {
    "github_actions": "GitHub Actions",
    "jenkins":        "Jenkins",
    "gitlab_ci":      "GitLab CI",
    "circleci":       "CircleCI",
    "bitbucket":      "Bitbucket Pipelines",
    "none":           "None detected",
}


# ── Connector ──────────────────────────────────────────────────────────────

class GitConnector:
    """Fetch repo metadata via HTTP API and classify project type."""

    def detect_project(
        self, git_url: str, token: str = "", branch: str = "main"
    ) -> ProjectTypeInfo:
        """
        Main entry point.
        Returns a ProjectTypeInfo describing the project and any CI/CD pipeline.
        Never raises — returns confidence="low" on errors.
        """
        try:
            provider, owner, repo = self.parse_url(git_url)
            log.info(f"[Git] Detecting {provider}/{owner}/{repo}@{branch}")

            if provider == "github":
                return self._detect_github(owner, repo, branch, token)
            if provider == "gitlab":
                return self._detect_gitlab(owner, repo, branch, token)
            return _unknown(f"Unsupported host in URL: {git_url}")

        except Exception as e:
            log.warning(f"[Git] Detection error: {e}")
            return _unknown(str(e))

    def get_workflows(self, git_url: str, token: str = "") -> list[dict]:
        """List GitHub Actions workflows (name, id, path) for a repository."""
        try:
            provider, owner, repo = self.parse_url(git_url)
            if provider != "github":
                return []
            data = self._gh(f"/repos/{owner}/{repo}/actions/workflows", token)
            return data.get("workflows", []) if isinstance(data, dict) else []
        except Exception:
            return []

    # ── GitHub ─────────────────────────────────────────────────────────────

    def _detect_github(self, owner, repo, branch, token) -> ProjectTypeInfo:
        root  = self._gh(f"/repos/{owner}/{repo}/contents?ref={branch}", token)
        files = {f["name"]: f for f in root} if isinstance(root, list) else {}

        cicd_type, cicd_files = self._cicd_github(owner, repo, branch, token, files)

        pom      = self._gh_file(owner, repo, "pom.xml",      branch, token)
        gradle   = self._gh_file(owner, repo, "build.gradle", branch, token) or \
                   self._gh_file(owner, repo, "build.gradle.kts", branch, token)
        pkg_json = self._gh_file(owner, repo, "package.json", branch, token)

        return _classify(pom, gradle, pkg_json, files, cicd_type, cicd_files)

    def _cicd_github(self, owner, repo, branch, token, root_files):
        cicd_type, cicd_files = "none", []

        # GitHub Actions takes priority
        if ".github" in root_files:
            try:
                wf = self._gh(
                    f"/repos/{owner}/{repo}/contents/.github/workflows?ref={branch}", token
                )
                if isinstance(wf, list):
                    yml = [f["path"] for f in wf if f["name"].endswith((".yml", ".yaml"))]
                    if yml:
                        return "github_actions", yml
            except Exception:
                pass

        for fname, ctype in [
            ("Jenkinsfile",              "jenkins"),
            (".gitlab-ci.yml",           "gitlab_ci"),
            (".circleci",                "circleci"),
            ("bitbucket-pipelines.yml",  "bitbucket"),
        ]:
            if fname in root_files:
                return ctype, [fname]

        return cicd_type, cicd_files

    def _gh(self, path: str, token: str):
        headers = {
            "Accept":     "application/vnd.github.v3+json",
            "User-Agent": "FileAnalyzer",
        }
        if token:
            headers["Authorization"] = f"token {token}"
        return _http_get(f"https://api.github.com{path}", headers)

    def _gh_file(self, owner, repo, path, branch, token) -> str:
        try:
            data = self._gh(f"/repos/{owner}/{repo}/contents/{path}?ref={branch}", token)
            if isinstance(data, dict) and data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            pass
        return ""

    # ── GitLab ─────────────────────────────────────────────────────────────

    def _detect_gitlab(self, owner, repo, branch, token) -> ProjectTypeInfo:
        proj_path = urllib.parse.quote(f"{owner}/{repo}", safe="")
        base      = f"https://gitlab.com/api/v4/projects/{proj_path}"
        hdrs      = {"User-Agent": "FileAnalyzer"}
        if token:
            hdrs["PRIVATE-TOKEN"] = token

        root  = _http_get(f"{base}/repository/tree?ref={branch}", hdrs)
        files = {f["name"]: f for f in (root if isinstance(root, list) else [])}

        cicd_type, cicd_files = "none", []
        for fname, ctype in [
            (".gitlab-ci.yml",          "gitlab_ci"),
            ("Jenkinsfile",             "jenkins"),
            (".circleci",               "circleci"),
            ("bitbucket-pipelines.yml", "bitbucket"),
        ]:
            if fname in files:
                cicd_type, cicd_files = ctype, [fname]
                break

        def read(fname):
            try:
                enc = urllib.parse.quote(fname, safe="")
                result = _http_get(f"{base}/repository/files/{enc}/raw?ref={branch}", hdrs)
                return result if isinstance(result, str) else ""
            except Exception:
                return ""

        pom      = read("pom.xml")      if "pom.xml"      in files else ""
        gradle   = read("build.gradle") if "build.gradle" in files else ""
        pkg_json = read("package.json") if "package.json" in files else ""

        return _classify(pom, gradle, pkg_json, files, cicd_type, cicd_files)

    # ── URL parser (public — used by Deployer) ─────────────────────────────

    def parse_url(self, url: str) -> tuple[str, str, str]:
        """
        Returns (provider, owner, repo) from any git URL format.
          https://github.com/owner/repo.git  →  ("github", "owner", "repo")
          git@github.com:owner/repo.git      →  ("github", "owner", "repo")
          https://gitlab.com/group/sub/repo  →  ("gitlab", "group/sub", "repo")
        """
        url = url.strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]

        if "github.com" in url:
            provider = "github"
        elif "gitlab.com" in url:
            provider = "gitlab"
        elif "bitbucket.org" in url:
            provider = "bitbucket"
        else:
            provider = "unknown"

        # SSH: git@github.com:owner/repo
        if url.startswith("git@"):
            path = url.split(":", 1)[-1]
        else:
            # HTTPS: strip everything up to .com/ or .org/
            for delim in [".com/", ".org/"]:
                if delim in url:
                    path = url.split(delim, 1)[1]
                    break
            else:
                path = url

        parts = path.strip("/").split("/")
        owner = "/".join(parts[:-1]) if len(parts) > 2 else (parts[0] if parts else "")
        repo  = parts[-1] if parts else ""
        return provider, owner, repo


# ── Classification logic ───────────────────────────────────────────────────

def _classify(pom: str, gradle: str, pkg_json: str,
              root_files: dict, cicd_type: str, cicd_files: list) -> ProjectTypeInfo:

    # ── Maven / Java ───────────────────────────────────────────────────────
    if pom:
        detected   = ["pom.xml"]
        is_spring  = "spring-boot" in pom.lower()
        is_war     = ("<packaging>war</packaging>" in pom
                      or "src/main/webapp" in pom
                      or "web.xml" in str(root_files))

        if is_spring and is_war:
            return _make("spring_boot_war", "maven",
                         "mvn clean package -DskipTests", "target/*.war",
                         "war_tomcat", cicd_type, cicd_files,
                         detected + ["spring-boot", "war"], "high")
        if is_spring:
            return _make("spring_boot_jar", "maven",
                         "mvn clean package -DskipTests", "target/*.jar",
                         "jar_service", cicd_type, cicd_files,
                         detected + ["spring-boot"], "high")
        if is_war:
            return _make("jsp_war", "maven",
                         "mvn clean package -DskipTests", "target/*.war",
                         "war_tomcat", cicd_type, cicd_files,
                         detected + ["war packaging"], "high")
        return _make("maven_jar", "maven",
                     "mvn clean package -DskipTests", "target/*.jar",
                     "jar_service", cicd_type, cicd_files, detected, "medium")

    # ── Gradle / Java ──────────────────────────────────────────────────────
    if gradle:
        detected  = ["build.gradle"]
        is_spring = ("spring-boot" in gradle.lower()
                     or "org.springframework.boot" in gradle)
        ptype     = "spring_boot_jar" if is_spring else "gradle_jar"
        return _make(ptype, "gradle",
                     "./gradlew clean build -x test", "build/libs/*.jar",
                     "jar_service", cicd_type, cicd_files,
                     detected + (["spring-boot"] if is_spring else []),
                     "high" if is_spring else "medium")

    # ── Node.js / Frontend ─────────────────────────────────────────────────
    if pkg_json:
        detected = ["package.json"]
        try:
            pkg = json.loads(pkg_json)
        except Exception:
            pkg = {}

        deps    = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        use_yarn = "yarn.lock" in root_files

        tool = "yarn" if use_yarn else "npm"
        install_cmd = f"{tool} install" if use_yarn else "npm ci"

        if "angular.json" in root_files or "@angular/core" in deps:
            return _make("angular", tool,
                         f"{install_cmd} && npm run build -- --configuration=production",
                         "dist/", "static_web", cicd_type, cicd_files,
                         detected + ["@angular/core"], "high")

        if "next" in deps:
            return _make("nextjs", tool,
                         f"{install_cmd} && npm run build",
                         ".next/", "node_server", cicd_type, cicd_files,
                         detected + ["next"], "high")

        if "react" in deps or "react-dom" in deps:
            return _make("react", tool,
                         f"{install_cmd} && npm run build",
                         "build/", "static_web", cicd_type, cicd_files,
                         detected + ["react"], "high")

        if "vue" in deps:
            return _make("vue", tool,
                         f"{install_cmd} && npm run build",
                         "dist/", "static_web", cicd_type, cicd_files,
                         detected + ["vue"], "high")

        return _make("nodejs", tool, install_cmd, ".",
                     "node_server", cicd_type, cicd_files, detected, "medium")

    return _unknown("No build file found (pom.xml / build.gradle / package.json)")


def _make(ptype, btool, bcmd, apath, dmethod,
          cicd_type, cicd_files, detected, confidence) -> ProjectTypeInfo:
    return ProjectTypeInfo(
        project_type=ptype, build_tool=btool,
        build_command=bcmd, artifact_path=apath,
        deploy_method=dmethod, cicd_type=cicd_type,
        cicd_files=cicd_files, detected_from=detected,
        confidence=confidence,
    )


def _unknown(reason: str) -> ProjectTypeInfo:
    return ProjectTypeInfo(
        project_type="unknown", build_tool="unknown",
        build_command="", artifact_path="", deploy_method="unknown",
        cicd_type="none", cicd_files=[],
        detected_from=[], confidence="low",
    )


def _http_get(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except Exception:
                return body
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        raise RuntimeError(f"Request failed for {url}: {e}")
