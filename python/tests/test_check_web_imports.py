"""`scripts/check_web_imports.py`, the web app's import boundary (step 4.3, D-83,
`08-code-design.md` section 1.5): an area imports its own files, `ui/`, `api/`, `charts/`, and
`app/`, never another area, through `@/` or a relative path; and `ui/`, `api/`, and `charts/`
import no area or `app/`, which would let one area reach another through them."""

from pathlib import Path

import check_web_imports


def write(source: Path, path: str, text: str) -> None:
    file = source / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")


def crossings(source: Path) -> list[str]:
    return [str(crossing) for crossing in check_web_imports.crossings_in(source)]


def test_an_area_may_import_its_own_files_the_shared_folders_and_the_app(tmp_path: Path) -> None:
    write(
        tmp_path,
        "areas/lab/LabPage.tsx",
        'import { Button } from "@/ui/button"\n'
        'import { api } from "@/api/client"\n'
        'import { router } from "../../app/router"\n'
        'import { useFeatures } from "./features"\n'
        'import "./lab.css"\n'
        'import { useQuery } from "@tanstack/react-query"\n',
    )

    assert crossings(tmp_path) == []


def test_an_import_of_another_area_is_refused_through_the_alias_or_a_relative_path(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        "areas/lab/LabPage.tsx",
        'import { RunsPage } from "@/areas/runs/RunsPage"\n'
        "import {\n  Settings,\n} from '../settings/SettingsPage'\n"
        'const prop = import("../prop/PropPage")\n',
    )

    assert crossings(tmp_path) == [
        "areas/lab/LabPage.tsx:1: Expected an import of lab's own files, ui/, api/, charts/, "
        "or app/, got '@/areas/runs/RunsPage', which is in areas/runs.",
        "areas/lab/LabPage.tsx:2: Expected an import of lab's own files, ui/, api/, charts/, "
        "or app/, got '../settings/SettingsPage', which is in areas/settings.",
        "areas/lab/LabPage.tsx:5: Expected an import of lab's own files, ui/, api/, charts/, "
        "or app/, got '../prop/PropPage', which is in areas/prop.",
    ]


def test_the_shared_folders_import_no_area_and_no_app(tmp_path: Path) -> None:
    write(tmp_path, "ui/button.tsx", 'import { cn } from "cn"\nimport { x } from "./x"\n')
    write(tmp_path, "api/client.ts", 'import { home } from "@/areas/home/HomePage"\n')
    write(tmp_path, "charts/line.tsx", 'export { router } from "../app/router"\n')

    assert crossings(tmp_path) == [
        "api/client.ts:1: Expected an import of ui/, api/, or charts/, got "
        "'@/areas/home/HomePage', which is in areas/home.",
        "charts/line.tsx:1: Expected an import of ui/, api/, or charts/, got '../app/router', "
        "which is in app.",
    ]


def test_the_app_and_the_entry_import_anything_and_comments_are_not_imports(
    tmp_path: Path,
) -> None:
    write(tmp_path, "main.tsx", 'import { router } from "./app/router"\nimport "./index.css"\n')
    write(tmp_path, "app/routes/lab.tsx", 'import { LabPage } from "@/areas/lab/LabPage"\n')
    write(tmp_path, "areas/home/HomePage.tsx", '// import { x } from "@/areas/lab/x"\n')

    assert crossings(tmp_path) == []


def test_generated_and_declaration_files_are_left_out(tmp_path: Path) -> None:
    write(tmp_path, "app/routeTree.gen.ts", 'import { x } from "../areas/lab/x"\n')
    write(tmp_path, "areas/lab/types.d.ts", 'import { y } from "@/areas/runs/y"\n')

    assert crossings(tmp_path) == []


def test_a_folders_index_counts_as_that_folder(tmp_path: Path) -> None:
    write(
        tmp_path,
        "areas/lab/LabPage.tsx",
        'import { lab } from "@/areas/lab"\n'
        'import { api } from "@/api"\n'
        'import { runs } from "@/areas/runs"\n',
    )

    assert crossings(tmp_path) == [
        "areas/lab/LabPage.tsx:3: Expected an import of lab's own files, ui/, api/, charts/, "
        "or app/, got '@/areas/runs', which is in areas/runs.",
    ]


def test_comments_and_line_breaks_inside_an_import_hide_nothing(tmp_path: Path) -> None:
    write(
        tmp_path,
        "areas/lab/LabPage.tsx",
        'import {\n  RunsPage, // don\'t use directly\n} from "@/areas/runs/RunsPage"\n'
        'const prop = import(\n  "@/areas/prop/PropPage"\n)\n',
    )

    assert [crossing.split(":")[1] for crossing in crossings(tmp_path)] == ["1", "4"]


def test_a_comment_marker_inside_a_string_hides_nothing(tmp_path: Path) -> None:
    write(
        tmp_path,
        "areas/lab/LabPage.tsx",
        'const pages = import.meta.glob("/src/areas/*/Page.tsx")\n'
        'const home = "http://127.0.0.1:8765/"\n'
        'import { RunsPage } from "@/areas/runs/RunsPage"\n'
        "/* the end */\n",
    )

    assert [crossing.split(":")[1] for crossing in crossings(tmp_path)] == ["3"]
