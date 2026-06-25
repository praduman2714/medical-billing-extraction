"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth-client";
import styles from "./dashboard.module.css";

interface BillingRecord {
  treatment_date?: string;
  date_of_service?: string;
  cpt_codes?: string[] | string;
  cpt_code?: string;
  description?: string;
  procedure_description?: string;
  provider?: string;
  provider_name?: string;
  insurers?: string[] | string;
  insurance_company?: string;
  charges?: number | string;
  total_charges?: number | string;
  paid?: number | string;
  amount_paid?: number | string;
  adjustment?: number | string;
  payments?: number | string;
  balance?: number | string;
  page?: number;
  page_number?: number;
}

interface FlaggedRecord {
  reason?: string;
  page?: number;
  page_number?: number;
  severity?: string;
}

interface JobResult {
  billing_records?: BillingRecord[];
  flagged_records?: FlaggedRecord[];
  [key: string]: any;
}

interface Job {
  id: string;
  status: string;
  pdf_filename: string;
  pdf_path: string;
  pdf_hash?: string;
  result?: JobResult | null;
  error?: string | null;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  } | null;
  cost_usd?: number | null;
  processing_duration_seconds?: number | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function DashboardPage() {
  const router = useRouter();
  const { data: session, isPending } = authClient.useSession();
  
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [errorModalJob, setErrorModalJob] = useState<Job | null>(null);
  const [copiedError, setCopiedError] = useState(false);
  const [modalTab, setModalTab] = useState<"records" | "flags">("records");
  const [isDragActive, setIsDragActive] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Redirect if not logged in
  useEffect(() => {
    if (!isPending && !session) {
      router.push("/auth/login");
    }
  }, [session, isPending, router]);

  // Fetch jobs and active job
  const fetchJobs = async () => {
    if (!session) return;
    try {
      const sessionResult = await authClient.getSession();
      const token = sessionResult.data?.session?.token;
      if (!token) return;

      const headers = { Authorization: `Bearer ${token}` };

      // Get list of jobs
      const res = await fetch(`${API_BASE_URL}/jobs/`, { headers });
      if (res.ok) {
        const payload = await res.json();
        if (payload.success) {
          setJobs(payload.data);
        }
      }

      // Get active job
      const activeRes = await fetch(`${API_BASE_URL}/jobs/active`, { headers });
      if (activeRes.ok) {
        const activePayload = await activeRes.json();
        if (activePayload.success) {
          setActiveJob(activePayload.data);
        }
      }
    } catch (err) {
      console.error("Error fetching jobs:", err);
    }
  };

  useEffect(() => {
    if (session) {
      fetchJobs();
    }
  }, [session]);

  // Auto-polling for pending/processing jobs
  useEffect(() => {
    if (!session) return;
    
    const hasUnfinishedJobs = jobs.some(
      (job) => job.status === "pending" || job.status === "processing"
    );

    if (hasUnfinishedJobs) {
      const interval = setInterval(() => {
        fetchJobs();
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [jobs, session]);

  // Handle Drag & Drop events
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.type === "application/pdf") {
        setSelectedFile(file);
        setUploadError(null);
      } else {
        setUploadError("Only PDF files are supported.");
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (file.type === "application/pdf") {
        setSelectedFile(file);
        setUploadError(null);
      } else {
        setUploadError("Only PDF files are supported.");
      }
    }
  };

  // Upload job
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !session) return;

    setUploading(true);
    setUploadError(null);

    try {
      const sessionResult = await authClient.getSession();
      const token = sessionResult.data?.session?.token;
      if (!token) throw new Error("No authentication session found.");

      const formData = new FormData();
      formData.append("file", selectedFile);

      const res = await fetch(`${API_BASE_URL}/jobs/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || "Failed to upload file.");
      }

      const payload = await res.json();
      if (payload.success) {
        setSelectedFile(null);
        fetchJobs();
      } else {
        throw new Error(payload.message || "Failed to upload file.");
      }
    } catch (err: any) {
      setUploadError(err.message || "An unexpected error occurred during upload.");
    } finally {
      setUploading(false);
    }
  };

  // Cancel pending job
  const handleCancelJob = async (jobId: string) => {
    if (!session) return;
    if (!confirm("Are you sure you want to cancel this pending job?")) return;

    try {
      const sessionResult = await authClient.getSession();
      const token = sessionResult.data?.session?.token;
      if (!token) return;

      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (res.ok) {
        fetchJobs();
      } else {
        const errorData = await res.json();
        alert(errorData.message || "Failed to cancel job.");
      }
    } catch (err: any) {
      alert(err.message || "Error cancelling job.");
    }
  };

  // Reprocess failed or cancelled job
  const handleReprocessJob = async (jobId: string) => {
    if (!session) return;
    try {
      const sessionResult = await authClient.getSession();
      const token = sessionResult.data?.session?.token;
      if (!token) return;

      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/reprocess`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (res.ok) {
        setErrorModalJob(null);
        fetchJobs();
      } else {
        const errorData = await res.json();
        alert(errorData.message || "Failed to trigger reprocessing.");
      }
    } catch (err: any) {
      alert(err.message || "Error reprocessing job.");
    }
  };

  const handleCopyError = (errorText: string) => {
    navigator.clipboard.writeText(errorText);
    setCopiedError(true);
    setTimeout(() => {
      setCopiedError(false);
    }, 2000);
  };


  const handleSignOut = async () => {
    await authClient.signOut({
      callbackURL: "/auth/login",
    });
    router.push("/auth/login");
  };

  // Format currency
  const formatUSD = (val: number | string | undefined | null) => {
    if (val === undefined || val === null) return "$0.00";
    const num = typeof val === "number" ? val : parseFloat(val);
    return isNaN(num) ? "$0.00" : `$${num.toFixed(2)}`;
  };

  if (isPending || !session) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <p style={{ color: "var(--foreground-muted)" }}>Loading platform dashboard...</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Navigation */}
      <nav className={styles.navbar}>
        <div className={styles.navLogo}>
          <div className={styles.logoIcon}>+</div>
          <span>Antigravity Billing RLS</span>
        </div>
        <div className={styles.navUser}>
          <div className={styles.userInfo}>
            <span className={styles.userName}>{session.user.name}</span>
            <span className={styles.userEmail}>{session.user.email}</span>
          </div>
          <button onClick={handleSignOut} className={styles.signOutBtn}>
            Sign Out
          </button>
        </div>
      </nav>

      {/* Main Grid */}
      <main className={styles.main}>
        {/* Left column: Upload Panel */}
        <section className={styles.uploadCard}>
          <h2 className={styles.panelTitle}>Upload Document</h2>
          
          <form onSubmit={handleUpload}>
            <div 
              className={`${styles.dropzone} ${isDragActive ? styles.dropzoneActive : ""}`}
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                style={{ display: "none" }}
                onChange={handleFileChange}
              />
              <div className={styles.dropzoneIcon}>⇪</div>
              <p className={styles.dropzoneText}>
                Drag & drop your medical bill PDF here or <strong>browse</strong>
              </p>
            </div>

            {uploadError && <div className={styles.error} style={{ marginTop: "16px" }}>{uploadError}</div>}

            {selectedFile && (
              <div className={styles.selectedFile}>
                <span className={styles.fileName}>{selectedFile.name}</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFile(null);
                  }}
                  className={styles.removeFileBtn}
                >
                  ✕
                </button>
              </div>
            )}

            <button
              type="submit"
              className={styles.processBtn}
              disabled={!selectedFile || uploading}
            >
              {uploading ? "Uploading & Enqueuing..." : "Process Billing Record"}
            </button>
          </form>
        </section>

        {/* Right column: Jobs History */}
        <section className={styles.historyPanel}>
          <h2 className={styles.panelTitle}>
            Extraction History
            {activeJob && (
              <span className={`${styles.badge} ${styles.badgeProcessing}`} style={{ fontSize: "11px", marginLeft: "12px" }}>
                Active processing: {activeJob.pdf_filename}
              </span>
            )}
          </h2>

          {jobs.length === 0 ? (
            <div className={styles.emptyState}>
              No extraction jobs found. Upload a medical bill to get started.
            </div>
          ) : (
            <div className={styles.jobsList}>
              {jobs.map((job) => (
                <div key={job.id} className={styles.jobCard}>
                  <div className={styles.jobInfo}>
                    <div className={styles.jobHeader}>
                      <span className={styles.jobTitle}>{job.pdf_filename}</span>
                      <span className={`
                        ${styles.badge}
                        ${job.status === "pending" ? styles.badgePending : ""}
                        ${job.status === "processing" ? styles.badgeProcessing : ""}
                        ${job.status === "completed" ? styles.badgeCompleted : ""}
                        ${job.status === "failed" ? styles.badgeFailed : ""}
                        ${job.status === "cancelled" ? styles.badgeCancelled : ""}
                      `}>
                        {job.status}
                      </span>
                    </div>

                    <div className={styles.jobMeta}>
                      <span>ID: {job.id}</span>
                      <span>•</span>
                      <span>Uploaded: {new Date(job.created_at).toLocaleString()}</span>
                    </div>

                    {(job.status === "completed" || job.status === "failed") && (
                      <div className={styles.jobMetrics}>
                        {job.cost_usd !== null && job.cost_usd !== undefined && (
                          <span>Cost: <strong className={styles.metricValue}>{formatUSD(job.cost_usd)}</strong></span>
                        )}
                        {job.token_usage && (
                          <span>Tokens: <strong className={styles.metricValue}>{job.token_usage.total_tokens.toLocaleString()}</strong></span>
                        )}
                        {job.processing_duration_seconds !== null && job.processing_duration_seconds !== undefined && (
                          <span>Duration: <strong className={styles.metricValue}>{job.processing_duration_seconds.toFixed(1)}s</strong></span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className={styles.jobActions}>
                    {job.status === "pending" && (
                      <button
                        onClick={() => handleCancelJob(job.id)}
                        className={`${styles.actionBtn} ${styles.btnDanger}`}
                      >
                        Cancel
                      </button>
                    )}
                    {job.status === "completed" && (
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setModalTab("records");
                        }}
                        className={`${styles.actionBtn} ${styles.btnPrimary}`}
                      >
                        View Extraction
                      </button>
                    )}
                    {job.status === "failed" && (
                      <div style={{ display: "flex", gap: "8px" }}>
                        <button
                          onClick={() => {
                            setErrorModalJob(job);
                            setCopiedError(false);
                          }}
                          className={`${styles.actionBtn} ${styles.btnSecondary}`}
                        >
                          View Error
                        </button>
                        <button
                          onClick={() => handleReprocessJob(job.id)}
                          className={`${styles.actionBtn} ${styles.btnPrimary}`}
                        >
                          Reprocess
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>

      {/* Extraction Detail Modal */}
      {selectedJob && (
        <div className={styles.modalOverlay} onClick={() => setSelectedJob(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Extraction: {selectedJob.pdf_filename}</h3>
              <button className={styles.modalClose} onClick={() => setSelectedJob(null)}>✕</button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.tabs}>
                <button
                  className={`${styles.tab} ${modalTab === "records" ? styles.tabActive : ""}`}
                  onClick={() => setModalTab("records")}
                >
                  Extracted Records ({selectedJob.result?.billing_records?.length || 0})
                </button>
                <button
                  className={`${styles.tab} ${modalTab === "flags" ? styles.tabActive : ""}`}
                  onClick={() => setModalTab("flags")}
                >
                  Manual Reviews ({selectedJob.result?.flagged_records?.length || 0})
                </button>
              </div>

              {modalTab === "records" ? (
                <div className={styles.tableContainer}>
                  {!selectedJob.result?.billing_records || selectedJob.result.billing_records.length === 0 ? (
                    <div className={styles.emptyState}>No billing records extracted.</div>
                  ) : (
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Provider</th>
                          <th>Description</th>
                          <th>CPT Code(s)</th>
                          <th>Charges</th>
                          <th>Paid</th>
                          <th>Adj</th>
                          <th>Balance</th>
                          <th>Page</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedJob.result.billing_records.map((rec, i) => {
                          const date = rec.treatment_date || rec.date_of_service || "-";
                          const prov = rec.provider || rec.provider_name || "-";
                          const desc = rec.description || rec.procedure_description || "-";
                          const cpt = Array.isArray(rec.cpt_codes)
                            ? rec.cpt_codes.join(", ")
                            : rec.cpt_code || (typeof rec.cpt_codes === "string" ? rec.cpt_codes : "-");
                          
                          const chargesVal = rec.charges !== undefined ? rec.charges : rec.total_charges;
                          const paidVal = rec.paid !== undefined ? rec.paid : rec.amount_paid;
                          const page = rec.page !== undefined ? rec.page : rec.page_number;

                          return (
                            <tr key={i}>
                              <td>{date}</td>
                              <td>{prov}</td>
                              <td style={{ maxWidth: "250px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{desc}</td>
                              <td>{cpt}</td>
                              <td>{formatUSD(chargesVal)}</td>
                              <td>{formatUSD(paidVal)}</td>
                              <td>{formatUSD(rec.adjustment)}</td>
                              <td>{formatUSD(rec.balance)}</td>
                              <td>{page !== undefined ? page : "-"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              ) : (
                <div className={styles.flaggedContainer}>
                  {!selectedJob.result?.flagged_records || selectedJob.result.flagged_records.length === 0 ? (
                    <div className={styles.emptyState}>No records require manual review.</div>
                  ) : (
                    selectedJob.result.flagged_records.map((flag, i) => {
                      const reason = flag.reason || "Manual review required.";
                      const severity = flag.severity || "warning";
                      const page = flag.page !== undefined ? flag.page : flag.page_number;

                      return (
                        <div key={i} className={styles.flaggedCard}>
                          <div className={styles.flaggedHeader}>
                            <span>SEVERITY: {severity.toUpperCase()}</span>
                            <span>PAGE: {page !== undefined ? page : "-"}</span>
                          </div>
                          <p className={styles.flaggedReason}>{reason}</p>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Error Detail Modal */}
      {errorModalJob && (
        <div className={styles.modalOverlay} onClick={() => setErrorModalJob(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Job Failed: {errorModalJob.pdf_filename}</h3>
              <button className={styles.modalClose} onClick={() => setErrorModalJob(null)}>✕</button>
            </div>

            <div className={styles.modalBody}>
              <p style={{ color: "var(--foreground-muted)", fontSize: "14px", marginBottom: "8px" }}>
                The extraction job failed with the following error. You can copy this error for troubleshooting or request to reprocess the document.
              </p>
              
              <div className={styles.errorBox}>
                {errorModalJob.error || "Unknown error occurred."}
              </div>

              <div className={styles.modalFooter}>
                <button
                  onClick={() => handleCopyError(errorModalJob.error || "Unknown error occurred.")}
                  className={`${styles.actionBtn} ${styles.btnSecondary}`}
                >
                  {copiedError ? "Copied!" : "Copy Error"}
                </button>
                <button
                  onClick={() => handleReprocessJob(errorModalJob.id)}
                  className={`${styles.actionBtn} ${styles.btnPrimary}`}
                >
                  Reprocess Job
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
