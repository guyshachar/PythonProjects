from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.response_error_details import ResponseErrorDetails


T = TypeVar("T", bound="ResponseError")


@_attrs_define
class ResponseError:
    """
    Attributes:
        status (Union[Unset, str]):  Example: error.
        message (Union[Unset, str]):
        details (Union[Unset, ResponseErrorDetails]):
    """

    status: Union[Unset, str] = UNSET
    message: Union[Unset, str] = UNSET
    details: Union[Unset, "ResponseErrorDetails"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status

        message = self.message

        details: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.details, Unset):
            details = self.details.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if status is not UNSET:
            field_dict["status"] = status
        if message is not UNSET:
            field_dict["message"] = message
        if details is not UNSET:
            field_dict["details"] = details

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.response_error_details import ResponseErrorDetails

        d = dict(src_dict)
        status = d.pop("status", UNSET)

        message = d.pop("message", UNSET)

        _details = d.pop("details", UNSET)
        details: Union[Unset, ResponseErrorDetails]
        if isinstance(_details, Unset):
            details = UNSET
        else:
            details = ResponseErrorDetails.from_dict(_details)

        response_error = cls(
            status=status,
            message=message,
            details=details,
        )

        response_error.additional_properties = d
        return response_error

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
