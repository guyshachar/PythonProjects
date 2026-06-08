from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="B14C21E0143Af0449Cfc94E58731C5A8Body")


@_attrs_define
class B14C21E0143Af0449Cfc94E58731C5A8Body:
    """
    Attributes:
        subscriber_id (int):
        signed_request (str):  Example: _1SXnOuwXiUrcDRxI1D6Dvr55aiNusDNMxyHb8PQe7Y.eyJhbGdvcml0aG0iOiJIT2FDLVNIQTI1NiIs
            ImNvbW11bml0eV9pZCI6bnVsbCwiaXNzdWVkX2F0IjoxNTU5MjE8NTQxLCJtZXRhZGF0YSI6bnVsbCwicGFnZV9pZCI6MjI4NjkwMDEyNDk2MTgx
            OSwicHNpZCI6IjIxNzI0OTkwNDI4Njc2MjIiLCJ0aHJlYWRfcGFydGljaXBhbnRfaWRzIjpudWxsLCJ0aHJlYWRfdHlwZSI6IlVTRVJfVE9fUEFH
            RSIsInRpZCI1IjIxNzI0OTkwNDI4Njc2MjIifQ.
    """

    subscriber_id: int
    signed_request: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        signed_request = self.signed_request

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
                "signed_request": signed_request,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        signed_request = d.pop("signed_request")

        b14c21e0143_af_0449_cfc_94e58731c5a8_body = cls(
            subscriber_id=subscriber_id,
            signed_request=signed_request,
        )

        b14c21e0143_af_0449_cfc_94e58731c5a8_body.additional_properties = d
        return b14c21e0143_af_0449_cfc_94e58731c5a8_body

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
