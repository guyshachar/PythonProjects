from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.field_637120a69445b2892f725_cbfeaf_347_ca_body_data import (
        Field637120A69445B2892F725Cbfeaf347CaBodyData,
    )


T = TypeVar("T", bound="Field637120A69445B2892F725Cbfeaf347CaBody")


@_attrs_define
class Field637120A69445B2892F725Cbfeaf347CaBody:
    """
    Attributes:
        user_ref (int):
        data (Field637120A69445B2892F725Cbfeaf347CaBodyData):
    """

    user_ref: int
    data: "Field637120A69445B2892F725Cbfeaf347CaBodyData"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        user_ref = self.user_ref

        data = self.data.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "user_ref": user_ref,
                "data": data,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.field_637120a69445b2892f725_cbfeaf_347_ca_body_data import (
            Field637120A69445B2892F725Cbfeaf347CaBodyData,
        )

        d = dict(src_dict)
        user_ref = d.pop("user_ref")

        data = Field637120A69445B2892F725Cbfeaf347CaBodyData.from_dict(d.pop("data"))

        field_637120a69445b2892f725_cbfeaf_347_ca_body = cls(
            user_ref=user_ref,
            data=data,
        )

        field_637120a69445b2892f725_cbfeaf_347_ca_body.additional_properties = d
        return field_637120a69445b2892f725_cbfeaf_347_ca_body

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
