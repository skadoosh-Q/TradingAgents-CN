export interface AnalysisModelSettings {
  quickAnalysisModel: string
  deepAnalysisModel: string
}

interface AvailableModel {
  enabled?: boolean
  provider: string
  model_name: string
}

interface CachedModelIdentity {
  provider: string
  modelName: string
}

interface CachedAnalysisModelSelection {
  version: 1
  quick: CachedModelIdentity
  deep: CachedModelIdentity
  updatedAt: string
}

const MODEL_SELECTION_CACHE_PREFIX = 'trading_analysis_model_selection'

const getCacheKey = (userId?: string | null): string | null => {
  return userId ? `${MODEL_SELECTION_CACHE_PREFIX}:${userId}` : null
}

const findModel = (models: AvailableModel[], identity: CachedModelIdentity) => {
  return models.find(model =>
    model.enabled !== false &&
    model.provider === identity.provider &&
    model.model_name === identity.modelName
  )
}

export const restoreAnalysisModelSelection = (
  userId: string | null | undefined,
  availableModels: AvailableModel[],
  defaults: AnalysisModelSettings
): AnalysisModelSettings => {
  const cacheKey = getCacheKey(userId)
  if (!cacheKey) return { ...defaults }

  try {
    const rawCache = localStorage.getItem(cacheKey)
    if (!rawCache) return { ...defaults }

    const cached = JSON.parse(rawCache) as CachedAnalysisModelSelection
    if (cached?.version !== 1 || !cached.quick || !cached.deep) {
      localStorage.removeItem(cacheKey)
      return { ...defaults }
    }

    const quickModel = findModel(availableModels, cached.quick)
    const deepModel = findModel(availableModels, cached.deep)

    return {
      quickAnalysisModel: quickModel?.model_name || defaults.quickAnalysisModel,
      deepAnalysisModel: deepModel?.model_name || defaults.deepAnalysisModel
    }
  } catch (error) {
    console.warn('读取模型选择缓存失败，使用系统默认模型:', error)
    localStorage.removeItem(cacheKey)
    return { ...defaults }
  }
}

export const saveAnalysisModelSelection = (
  userId: string | null | undefined,
  availableModels: AvailableModel[],
  selection: AnalysisModelSettings
) => {
  const cacheKey = getCacheKey(userId)
  if (!cacheKey) return

  const quickModel = availableModels.find(
    model => model.enabled !== false && model.model_name === selection.quickAnalysisModel
  )
  const deepModel = availableModels.find(
    model => model.enabled !== false && model.model_name === selection.deepAnalysisModel
  )
  if (!quickModel || !deepModel) return

  const cacheData: CachedAnalysisModelSelection = {
    version: 1,
    quick: {
      provider: quickModel.provider,
      modelName: quickModel.model_name
    },
    deep: {
      provider: deepModel.provider,
      modelName: deepModel.model_name
    },
    updatedAt: new Date().toISOString()
  }

  localStorage.setItem(cacheKey, JSON.stringify(cacheData))
}
