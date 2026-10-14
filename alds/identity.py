import numpy as np
from imgutils.metrics import ccip_batch_differences, ccip_batch_extract_features

from .cancel import check as check_cancel


def ccip_features(images, batch=32) -> np.ndarray:
    out = []
    for i in range(0, len(images), batch):
        check_cancel()
        out.append(ccip_batch_extract_features(images[i:i + batch]))
    return np.concatenate(out).astype(np.float32)


def ccip_cross(A: np.ndarray, B: np.ndarray, block=1024) -> np.ndarray:
    out = np.empty((len(A), len(B)), np.float32)
    for i in range(0, len(A), block):
        a = A[i:i + block]
        for j in range(0, len(B), block):
            check_cancel()
            b = B[j:j + block]
            m = ccip_batch_differences(list(np.concatenate([a, b])))
            out[i:i + len(a), j:j + len(b)] = m[:len(a), len(a):]
    return out


def ccip_matrix(F: np.ndarray) -> np.ndarray:
    D = ccip_cross(F, F)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0)
    return np.clip(D, 0, None)
