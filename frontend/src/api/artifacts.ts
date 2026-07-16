import { API_BASE_URL } from './client'

export function getArtifactUrl(artifactId: string): string {
  return `${API_BASE_URL}/artifacts/${encodeURIComponent(artifactId)}/download`
}
