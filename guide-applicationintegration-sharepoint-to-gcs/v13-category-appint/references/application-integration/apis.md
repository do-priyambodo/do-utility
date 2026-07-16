{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "_shared/templates/_doc_specific_landing_page.html" %}

{% block pagevariables %}


{% include "application-integration/_local_variables.html" %}

{% setvar landing_page_title %}APIs and reference{% endsetvar %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="description" content="Get details about client libraries and APIs" />

{% endblock %}

{% block doclinks %}

<div class="card" id="authentication">
  <header>
    <h2>Authentication</h2>
  </header>
  <ul class="card-showcase">

    {% setvar lp_title %}Authenticate to {{product_name_short}} {% endsetvar %}
    {% setvar lp_link%}{{ root_path }}docs/authentication{% endsetvar %}
    {% setvar lp_desc %}
    This document describes how to authenticate to {{product_name_short}} if you
    are using REST.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

  </ul>
</div>

<div class="card" id="ip-api">
  <header>
    <h2>{{product_name_short}} API</h2>
  </header>
  <ul class="card-showcase">

    {% setvar lp_title %}V1 API reference{% endsetvar %}
    {% setvar lp_link%}{{ root_path }}docs/reference/rest{% endsetvar %}
    {% setvar lp_desc %}
    Programming reference for the V1 {{product_name_short}} API.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}V2 API reference{% endsetvar %}
    {% setvar lp_link%}{{ root_path }}docs/reference/rest{% endsetvar %}
    {% setvar lp_desc %}
    Programming reference for the V2 {{product_name_short}} API.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

  </ul>
</div>

{% endblock %}
