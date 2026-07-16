import { describe, expect, it } from 'vitest'
import { defaultFormValues, toBatchCreateRequest } from './configReducer'

describe('toBatchCreateRequest', () => {
  it('maps the complete UI form to the OpenAPI snake_case contract', () => {
    const values = {
      ...defaultFormValues,
      outputDirectory: '  ./exports  ',
      concurrency: 3,
      narration: {
        enabled: true,
        language: 'zh-TW' as const,
        voiceId: 'voice-01',
        voicePrompt: '  克制、悬疑  ',
      },
      deduplication: {
        ...defaultFormValues.deduplication,
        colorNoiseTweak: true,
        borderMode: 'blurred' as const,
        speedTweak: true,
      },
    }

    expect(toBatchCreateRequest(values, ['upload-1'])).toEqual({
      upload_ids: ['upload-1'],
      output_directory: './exports',
      concurrency: 3,
      narration: {
        enabled: true,
        language: 'zh-TW',
        voice_id: 'voice-01',
        voice_prompt: '克制、悬疑',
      },
      deduplication: {
        change_file_hash: true,
        reencode: true,
        color_noise_tweak: true,
        border_mode: 'blurred',
        sticker: false,
        subtitle_mask: false,
        crop_scale: false,
        mirror: false,
        speed_tweak: true,
      },
    })
  })

  it('omits optional voice fields when narration is disabled', () => {
    const request = toBatchCreateRequest(defaultFormValues, ['upload-1'])
    expect(request.narration).toEqual({ enabled: false, language: 'zh-CN' })
  })
})
