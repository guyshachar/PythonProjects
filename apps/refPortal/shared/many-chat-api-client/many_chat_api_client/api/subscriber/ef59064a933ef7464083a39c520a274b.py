from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.ef_59064a933_ef_7464083a39c520a274b_response_200 import Ef59064A933Ef7464083A39C520A274BResponse200
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    email: Union[Unset, str] = UNSET,
    phone: Union[Unset, str] = UNSET,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["email"] = email

    params["phone"] = phone

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/subscriber/findBySystemField",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Ef59064A933Ef7464083A39C520A274BResponse200]:
    if response.status_code == 200:
        response_200 = Ef59064A933Ef7464083A39C520A274BResponse200.from_dict(response.json())

        return response_200
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Ef59064A933Ef7464083A39C520A274BResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    email: Union[Unset, str] = UNSET,
    phone: Union[Unset, str] = UNSET,
) -> Response[Ef59064A933Ef7464083A39C520A274BResponse200]:
    """***Limit:*** 50 queries per second.<br>Set one parameter: Email OR Phone.

    Args:
        email (Union[Unset, str]):
        phone (Union[Unset, str]):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Ef59064A933Ef7464083A39C520A274BResponse200]
    """

    kwargs = _get_kwargs(
        email=email,
        phone=phone,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    email: Union[Unset, str] = UNSET,
    phone: Union[Unset, str] = UNSET,
) -> Optional[Ef59064A933Ef7464083A39C520A274BResponse200]:
    """***Limit:*** 50 queries per second.<br>Set one parameter: Email OR Phone.

    Args:
        email (Union[Unset, str]):
        phone (Union[Unset, str]):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Ef59064A933Ef7464083A39C520A274BResponse200
    """

    return sync_detailed(
        client=client,
        email=email,
        phone=phone,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    email: Union[Unset, str] = UNSET,
    phone: Union[Unset, str] = UNSET,
) -> Response[Ef59064A933Ef7464083A39C520A274BResponse200]:
    """***Limit:*** 50 queries per second.<br>Set one parameter: Email OR Phone.

    Args:
        email (Union[Unset, str]):
        phone (Union[Unset, str]):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Ef59064A933Ef7464083A39C520A274BResponse200]
    """

    kwargs = _get_kwargs(
        email=email,
        phone=phone,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    email: Union[Unset, str] = UNSET,
    phone: Union[Unset, str] = UNSET,
) -> Optional[Ef59064A933Ef7464083A39C520A274BResponse200]:
    """***Limit:*** 50 queries per second.<br>Set one parameter: Email OR Phone.

    Args:
        email (Union[Unset, str]):
        phone (Union[Unset, str]):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Ef59064A933Ef7464083A39C520A274BResponse200
    """

    return (
        await asyncio_detailed(
            client=client,
            email=email,
            phone=phone,
        )
    ).parsed
