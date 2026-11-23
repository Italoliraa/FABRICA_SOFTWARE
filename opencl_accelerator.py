"""OpenCL acceleration for independent schedule-slot filtering.

OpenCL is optional at runtime. The application remains usable on machines
without an OpenCL driver by using the equivalent Python implementation.
"""

from __future__ import annotations

import logging
from threading import Lock

LOGGER = logging.getLogger(__name__)

_KERNEL_SOURCE = """
// Cada item da grade e processado em paralelo pelo dispositivo OpenCL.
// 1 significa que o horario esta livre; 0 significa que esta ocupado.
__kernel void filter_slots(
    __global const uchar *occupied,
    __global uchar *available,
    const uint slot_count
) {
    const uint index = get_global_id(0);
    if (index < slot_count) {
        available[index] = occupied[index] == 0;
    }
}
"""

_backend_lock = Lock()
_backend = None
_backend_error = None


# Inicializa o ambiente OpenCL uma unica vez, escolhendo uma GPU quando
# disponivel e mantendo o fallback para CPU quando nao houver suporte.
def _load_backend():
    global _backend, _backend_error

    if _backend is not None or _backend_error is not None:
        return _backend

    with _backend_lock:
        if _backend is not None or _backend_error is not None:
            return _backend
        try:
            import numpy as np
            import pyopencl as cl
        except ImportError as exc:
            _backend_error = str(exc)
            LOGGER.warning("OpenCL indisponivel; usando processamento da CPU: %s", exc)
            return _backend

        try:
            platforms = cl.get_platforms()
            devices = [
                device
                for platform in platforms
                for device in platform.get_devices()
            ]
            if not devices:
                raise RuntimeError("Nenhum dispositivo OpenCL foi encontrado.")

            device = next(
                (item for item in devices if item.type & cl.device_type.GPU),
                devices[0],
            )
            context = cl.Context([device])
            queue = cl.CommandQueue(context)
            program = cl.Program(context, _KERNEL_SOURCE).build()
            _backend = (np, cl, context, queue, program, device)
            LOGGER.info("OpenCL habilitado no dispositivo %s.", device.name)
        except (cl.Error, RuntimeError, OSError) as exc:
            _backend_error = str(exc)
            LOGGER.warning("OpenCL indisponivel; usando processamento da CPU: %s", exc)

    return _backend


# Filtra os horarios ocupados em paralelo no OpenCL e retorna os horarios
# livres na mesma ordem da grade original.
def filter_available_slots(slots, occupied):
    """Return free slots, using OpenCL when a device is available.

    ``slots`` must preserve the application's chronological order and
    ``occupied`` contains the slot values already booked.
    """
    occupied_set = set(occupied)
    backend = _load_backend()
    if backend is None:
        return [slot for slot in slots if slot not in occupied_set]

    np, cl, context, queue, program, _device = backend
    occupied_flags = np.asarray(
        [slot in occupied_set for slot in slots],
        dtype=np.uint8,
    )
    available_flags = np.empty(len(slots), dtype=np.uint8)
    occupied_buffer = cl.Buffer(
        context,
        cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
        hostbuf=occupied_flags,
    )
    available_buffer = cl.Buffer(
        context,
        cl.mem_flags.WRITE_ONLY,
        available_flags.nbytes,
    )
    program.filter_slots(
        queue,
        (len(slots),),
        None,
        occupied_buffer,
        available_buffer,
        np.uint32(len(slots)),
    )
    cl.enqueue_copy(queue, available_flags, available_buffer).wait()
    return [
        slot
        for slot, available in zip(slots, available_flags)
        if available
    ]


# Informa se o backend OpenCL foi ativado e qual dispositivo esta sendo usado.
def backend_status():
    """Return diagnostic information for the application health endpoint."""
    backend = _load_backend()
    if backend is None:
        return {"enabled": False, "error": _backend_error}
    return {"enabled": True, "device": backend[5].name.strip()}
