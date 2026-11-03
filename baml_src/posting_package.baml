class PostingPackage {
  captions string[]
  hashtags string[]
}

function WritePostingPackage(product_json: string, brief_json: string) -> PostingPackage {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You write the text that goes with a short vertical affiliate video on TikTok Shop Vietnam.
    Return JSON only and exactly match the response schema.

    captions: exactly 3 different caption options in natural Vietnamese for Vietnamese shoppers.
    Each one starts with a hook in the first 8 words, stays under 220 characters, speaks to the
    target audience of the brief, follows its selling angle, ends with a short call to action to
    open the product link, and contains at most 2 emojis. The 3 options must differ in tone and
    hook.

    hashtags: 8 to 10 hashtags, each starting with #, lowercase, no spaces, mixing broad ones
    (for example about TikTok Shop and shopping) with ones specific to the product type and its
    use. No duplicates.

    Every number, price, percentage, material or feature must come from the product facts or
    the brief; never invent figures, certifications, medical or guaranteed-result claims. Do not
    use absolute claims such as "number 1" or "best in Vietnam", and do not mention competitors.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Brief:
    {{ brief_json }}

    {{ ctx.output_format }}
  "#
}
