import type { BatchCreateRequest } from '../../api/contracts'
import type { BatchFormValues } from './types'

export const defaultFormValues: BatchFormValues = {
  outputDirectory: './storage/outputs',
  concurrency: 1,
  narration: {
    enabled: false,
    language: 'zh-CN',
    voiceId: '',
    voicePrompt: '',
  },
  deduplication: {
    changeFileHash: true,
    reencode: true,
    colorNoiseTweak: false,
    borderMode: 'none',
    sticker: false,
    subtitleMask: false,
    cropScale: false,
    mirror: false,
    speedTweak: false,
  },
}

export type ConfigAction =
  | { type: 'set'; path: string; value: string | number | boolean }
  | { type: 'reset' }

export function configReducer(
  state: BatchFormValues,
  action: ConfigAction,
): BatchFormValues {
  if (action.type === 'reset') return defaultFormValues
  const [group, key] = action.path.split('.')
  if (!key) return { ...state, [group]: action.value }
  if (group === 'narration') {
    return { ...state, narration: { ...state.narration, [key]: action.value } }
  }
  if (group === 'deduplication') {
    return {
      ...state,
      deduplication: { ...state.deduplication, [key]: action.value },
    }
  }
  return state
}

export function toBatchCreateRequest(
  values: BatchFormValues,
  uploadIds: string[],
): BatchCreateRequest {
  const narration = values.narration.enabled
    ? {
        enabled: true,
        language: values.narration.language,
        ...(values.narration.voiceId.trim()
          ? { voice_id: values.narration.voiceId.trim() }
          : {}),
        ...(values.narration.voicePrompt.trim()
          ? { voice_prompt: values.narration.voicePrompt.trim() }
          : {}),
      }
    : { enabled: false, language: values.narration.language }

  return {
    upload_ids: uploadIds,
    output_directory: values.outputDirectory.trim(),
    concurrency: values.concurrency,
    narration,
    deduplication: {
      change_file_hash: values.deduplication.changeFileHash,
      reencode: values.deduplication.reencode,
      color_noise_tweak: values.deduplication.colorNoiseTweak,
      border_mode: values.deduplication.borderMode,
      sticker: values.deduplication.sticker,
      subtitle_mask: values.deduplication.subtitleMask,
      crop_scale: values.deduplication.cropScale,
      mirror: values.deduplication.mirror,
      speed_tweak: values.deduplication.speedTweak,
    },
  }
}
