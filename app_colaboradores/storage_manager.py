from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
import uuid

from app_config import BASE_DIR, STORAGE_ROOT


class FileMutationJournal:
    """Compensating filesystem transaction for DB-backed attachment changes.

    New files are copied to staging first. Deleted files/directories are moved to
    a recoverable trash area and restored automatically unless ``complete`` is
    called after the database commit.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_storage_root_path()).resolve()
        self.transaction_id = uuid.uuid4().hex
        self.work_root = self.root / ".transactions" / self.transaction_id
        self.staging_root = self.work_root / "staging"
        self.trash_root = self.work_root / "trash"
        self._additions: list[tuple[Path, Path]] = []
        self._deleted: list[tuple[Path, Path]] = []
        self._moves: list[tuple[Path, Path]] = []
        self._promoted: list[Path] = []
        self._completed = False

    def __enter__(self):
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.trash_root.mkdir(parents=True, exist_ok=True)
        return self

    def stage_file(self, source_path: str, category: str, codigo_colaborador: str | None = None) -> str:
        source = Path(source_path).expanduser()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Arquivo nao encontrado: {source_path}")
        relative = build_managed_relative_path(source_path, category, codigo_colaborador)
        staged = self.staging_root / uuid.uuid4().hex
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, staged)
        final = self.root / relative
        self._additions.append((staged, final))
        return relative.as_posix()

    def promote(self) -> None:
        for staged, final in self._additions:
            if not staged.exists():
                continue
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                raise FileExistsError(f"Destino de anexo ja existe: {final}")
            staged.replace(final)
            self._promoted.append(final)

    def stage_delete_path(self, path: str | Path | None) -> bool:
        if not path:
            return False
        original = Path(path).resolve()
        try:
            original.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Caminho fora do storage gerenciado: {original}") from exc
        if not original.exists():
            return False
        trashed = self.trash_root / f"{uuid.uuid4().hex}_{original.name}"
        trashed.parent.mkdir(parents=True, exist_ok=True)
        original.replace(trashed)
        self._deleted.append((trashed, original))
        return True

    def stage_delete_reference(self, stored_path: str | None) -> bool:
        if not stored_path or not is_managed_path(stored_path):
            return False
        return self.stage_delete_path(resolve_stored_path(stored_path))

    def stage_delete_category(self, category: str, codigo_colaborador: str) -> bool:
        return self.stage_delete_path(get_category_dir(category, codigo_colaborador))

    def move_path(self, source: str | Path, destination: str | Path) -> bool:
        source_path = Path(source).resolve()
        destination_path = Path(destination).resolve()
        try:
            source_path.relative_to(self.root)
            destination_path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Movimentacao fora do storage gerenciado nao permitida.") from exc
        if not source_path.exists() or source_path == destination_path:
            return False
        if destination_path.exists():
            raise FileExistsError(f"Destino ja existe: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination_path)
        self._moves.append((destination_path, source_path))
        return True

    def complete(self) -> None:
        self._completed = True
        try:
            shutil.rmtree(self.work_root)
        except OSError:
            # Trash retained is recoverable and can be cleaned by maintenance.
            pass

    def rollback(self) -> None:
        for current, original in reversed(self._moves):
            if current.exists() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                current.replace(original)
        for trashed, original in reversed(self._deleted):
            if trashed.exists() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                trashed.replace(original)
        for final in reversed(self._promoted):
            try:
                if final.is_file():
                    final.unlink()
                elif final.is_dir():
                    shutil.rmtree(final)
            except OSError:
                pass

    def __exit__(self, exc_type, exc, tb):
        if not self._completed:
            self.rollback()
        try:
            shutil.rmtree(self.work_root)
        except OSError:
            pass
        return False


def _sanitize_segment(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    normalized = normalized.strip("._")
    return normalized or fallback


def get_storage_root_path() -> Path:
    return Path(STORAGE_ROOT).resolve()


def get_category_dir(category: str, codigo_colaborador: str | None = None) -> Path:
    base = get_storage_root_path() / _sanitize_segment(category, "arquivos")
    if codigo_colaborador:
        base = base / _sanitize_segment(codigo_colaborador, "sem_codigo")
    return base


def build_managed_relative_path(
    source_path: str,
    category: str,
    codigo_colaborador: str | None = None,
) -> Path:
    source = Path(source_path).expanduser()
    extension = source.suffix.lower()
    stem = _sanitize_segment(source.stem, "arquivo")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    filename = f"{timestamp}_{stem}_{unique}{extension}"
    relative = Path(_sanitize_segment(category, "arquivos"))
    if codigo_colaborador:
        relative /= _sanitize_segment(codigo_colaborador, "sem_codigo")
    return relative / filename


def store_file(
    source_path: str,
    category: str,
    codigo_colaborador: str | None = None,
) -> str:
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Arquivo nao encontrado: {source_path}")

    destination_relative = build_managed_relative_path(source_path, category, codigo_colaborador)
    destination_absolute = get_storage_root_path() / destination_relative
    destination_absolute.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination_absolute)
    return destination_relative.as_posix()


def copy_file_to_relative_path(source_path: str, relative_path: str) -> str:
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Arquivo nao encontrado: {source_path}")

    normalized_relative = Path(relative_path)
    destination_absolute = get_storage_root_path() / normalized_relative
    destination_absolute.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination_absolute)
    return normalized_relative.as_posix()


def resolve_stored_path(stored_path: str | None) -> str:
    if not stored_path:
        return ""

    raw = Path(str(stored_path)).expanduser()
    if raw.is_absolute():
        return str(raw.resolve())

    candidates = [
        get_storage_root_path() / raw,
        BASE_DIR / raw,
        Path.cwd() / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return str(candidates[0].resolve())


def is_managed_path(stored_path: str | None) -> bool:
    if not stored_path:
        return False

    resolved = Path(resolve_stored_path(stored_path))
    try:
        resolved.relative_to(get_storage_root_path())
        return True
    except ValueError:
        return False


def normalize_storage_reference(stored_path: str | None) -> str:
    if not stored_path:
        return ""

    resolved = Path(resolve_stored_path(stored_path))
    try:
        return resolved.relative_to(get_storage_root_path()).as_posix()
    except ValueError:
        return str(stored_path)


def delete_managed_file(stored_path: str | None) -> bool:
    if not stored_path or not is_managed_path(stored_path):
        return False

    target = Path(resolve_stored_path(stored_path))
    if not target.exists() or not target.is_file():
        return False

    target.unlink()
    _cleanup_empty_dirs(target.parent)
    return True


def delete_category_dir(category: str, codigo_colaborador: str) -> bool:
    target_dir = get_category_dir(category, codigo_colaborador)
    if not target_dir.exists() or not target_dir.is_dir():
        return False

    shutil.rmtree(target_dir)
    _cleanup_empty_dirs(target_dir.parent)
    return True


def _cleanup_empty_dirs(directory: Path) -> None:
    root = get_storage_root_path()
    current = directory
    while current != root and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
