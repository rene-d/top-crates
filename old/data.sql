
CREATE TABLE dependencies (
    id integer PRIMARY KEY NOT NULL,
    version_id integer NOT NULL,
    crate_id integer NOT NULL,
    req text NOT NULL,
    optional boolean NOT NULL,
    default_features boolean NOT NULL,
    features text NOT NULL,
    target text,
    kind integer DEFAULT 0 NOT NULL
);

CREATE TABLE crates (
    id integer PRIMARY KEY NOT NULL,
    name text NOT NULL,
    updated_at timestamp NOT NULL,
    created_at timestamp NOT NULL,
    downloads integer DEFAULT 0 NOT NULL,
    description text,
    homepage text,
    documentation text,
    readme text ,
    repository text ,
    max_upload_size integer NOT NULL
);

CREATE TABLE version_downloads (
    version_id integer NOT NULL,
    downloads integer DEFAULT 1 NOT NULL,
    date timestamp NOT NULL
);

CREATE TABLE versions (
    id integer NOT NULL,
    crate_id integer NOT NULL,
    num text NOT NULL,
    updated_at timestamp NOT NULL,
    created_at timestamp NOT NULL,
    downloads integer DEFAULT 0 NOT NULL,
    features text NOT NULL,
    yanked boolean DEFAULT false NOT NULL,
    license text,
    crate_size integer,
    published_by integer
);

CREATE INDEX index_versions_crate_id ON versions (crate_id);
CREATE INDEX index_dependencies_version_id ON dependencies (version_id);
CREATE INDEX dependencies_crate_id_version_id_idx ON dependencies (crate_id, version_id);


-- .mode csv
-- .import --skip 1 data/crates.csv crates
-- .import --skip 1 data/version_downloads.csv version_downloads
-- .import --skip 1 data/versions.csv versions
-- .import --skip 1 data/dependencies.csv dependencies
