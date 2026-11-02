class ReferenceSearchProfileDraft {
  product_type string
  keywords string[]
}

function DraftReferenceSearchProfile(product_json: string) -> ReferenceSearchProfileDraft {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You prepare image-reference searches for affiliate content on TikTok Shop Vietnam.
    From the product facts, return the generic product type and Pinterest search queries
    for visual inspiration of the product's marketing photos: style, composition and setting.
    Do not use brand names. Return JSON only and exactly match the response schema.

    product_type: short generic type in lowercase Vietnamese, for example "máy cạo râu".
    keywords: 3 to 5 Pinterest queries mixing Vietnamese and English.

    {{ _.role("user") }}
    {{ product_json }}

    {{ ctx.output_format }}
  "#
}
