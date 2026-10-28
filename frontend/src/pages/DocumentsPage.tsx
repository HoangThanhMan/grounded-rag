import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, deleteDocument, listDocuments, uploadDocument } from "../api";
import { viDate } from "../format";
import type { LibraryDocument } from "../types";

const KEY_STORAGE = "grounded-rag.admin-key";
const STATUS: Record<LibraryDocument["status"], string> = {
  processing: "Đang lập chỉ mục",
  ready: "Sẵn sàng",
  failed: "Lỗi",
};

function storedKey(): string {
  try {
    return sessionStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

function storeKey(key: string) {
  try {
    sessionStorage.setItem(KEY_STORAGE, key);
  } catch {
    // private mode: the key just is not remembered
  }
}

export function DocumentsPage() {
  const [docs, setDocs] = useState<LibraryDocument[] | null>(null);
  const [adminKey, setAdminKey] = useState(storedKey);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(() => {
    listDocuments()
      .then(setDocs)
      .catch(() => setError("Không tải được danh sách văn bản."));
  }, []);

  useEffect(load, [load]);

  // poll only while something is still being indexed
  const indexing = docs?.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!indexing) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [indexing, load]);

  function explain(err: unknown): string {
    if (err instanceof ApiError && err.status === 401) return "Admin key không đúng.";
    if (err instanceof ApiError && err.status === 403)
      return "Máy chủ chưa bật quản lý văn bản (thiếu ADMIN_API_KEY).";
    if (err instanceof ApiError && err.status === 413) return "Tệp lớn hơn 10 MB.";
    if (err instanceof ApiError) return err.message;
    return "Không kết nối được máy chủ.";
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    for (const [k, v] of [...data.entries()]) if (v === "") data.delete(k);
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(data, adminKey);
      form.reset();
      load();
    } catch (err) {
      setError(explain(err));
    } finally {
      setUploading(false);
    }
  }

  async function remove(doc: LibraryDocument) {
    if (!window.confirm(`Xoá "${doc.title}" khỏi thư viện? Hệ thống sẽ không trả lời theo văn bản này nữa.`))
      return;
    setError(null);
    try {
      await deleteDocument(doc.id, adminKey);
      load();
    } catch (err) {
      setError(explain(err));
    }
  }

  return (
    <main className="library">
      <h1>Văn bản trong thư viện</h1>
      <p className="library-lead">
        Hệ thống chỉ trả lời theo các văn bản dưới đây, và chỉ theo điều khoản còn hiệu lực vào
        ngày bạn chọn khi hỏi.
      </p>

      {error && <p className="notice" role="alert">{error}</p>}

      {docs === null ? (
        <p className="muted">Đang tải…</p>
      ) : docs.length === 0 ? (
        <p className="muted">Thư viện chưa có văn bản nào. Tải một văn bản lên bên dưới.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Văn bản</th>
                <th>Hiệu lực</th>
                <th>Trạng thái</th>
                {adminKey && <th aria-label="Thao tác" />}
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>
                    <span className="doc-title">{d.title}</span>
                    {d.number && <span className="doc-number">Số {d.number}</span>}
                  </td>
                  <td>
                    {d.effective_date ? `Từ ${viDate(d.effective_date)}` : "Chưa rõ"}
                    {d.expiry_date && <span className="doc-expired">Hết hiệu lực {viDate(d.expiry_date)}</span>}
                  </td>
                  <td>
                    <span className={`status status-${d.status}`}>{STATUS[d.status]}</span>
                    {d.status === "ready" && <span className="muted"> {d.chunks} đoạn</span>}
                    {d.error && <span className="doc-error">{d.error}</span>}
                  </td>
                  {adminKey && (
                    <td>
                      <button type="button" className="btn btn-quiet" onClick={() => remove(d)}>
                        Xoá
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section className="admin">
        <h2>Thêm văn bản</h2>
        <label className="field">
          Admin key
          <input
            type="password"
            value={adminKey}
            autoComplete="off"
            onChange={(e) => {
              setAdminKey(e.target.value);
              storeKey(e.target.value);
            }}
          />
        </label>
        {adminKey && (
          <form className="upload" onSubmit={upload}>
            <label className="field field-wide">
              Tệp .md hoặc .pdf, tối đa 10 MB
              <input type="file" name="file" accept=".md,.pdf" required />
            </label>
            <label className="field field-wide">
              Tên văn bản
              <input name="title" placeholder="Để trống thì lấy từ tệp" />
            </label>
            <label className="field">
              Số hiệu
              <input name="number" placeholder="45/2019/QH14" />
            </label>
            <label className="field">
              Có hiệu lực từ
              <input type="date" name="effective_date" />
            </label>
            <label className="field">
              Hết hiệu lực
              <input type="date" name="expiry_date" />
            </label>
            <p className="upload-hint">
              Tải lại một tệp cùng tên sẽ thay văn bản cũ. Văn bản cần giữ cấu trúc "Điều …" và
              "1. …" ở đầu dòng để được chia theo điều khoản.
            </p>
            <button type="submit" className="btn btn-primary" disabled={uploading}>
              {uploading ? "Đang tải lên…" : "Tải lên và lập chỉ mục"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
