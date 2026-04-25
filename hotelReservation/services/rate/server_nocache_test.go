//go:build no_memcache

package rate

import (
	"context"
	"errors"
	"reflect"
	"testing"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/rate/proto"
	"go.mongodb.org/mongo-driver/mongo"
	"pgregory.net/rapid"
)

func TestNoMemcacheGetRatesProperty(t *testing.T) {
	oldGetRatesFromMongo := getRatesFromMongo
	t.Cleanup(func() {
		getRatesFromMongo = oldGetRatesFromMongo
	})

	var calls []string
	getRatesFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (RatePlans, error) {
		calls = append(calls, hotelId)
		totalRate := float64(len(hotelId)*100 + len(calls))
		return RatePlans{
			{
				HotelId: hotelId,
				Code:    "RACK",
				RoomType: &pb.RoomType{
					TotalRate: totalRate,
				},
			},
		}, nil
	}

	rapid.Check(t, func(t *rapid.T) {
		hotelIds := rapid.SliceOfN(rapid.StringMatching(`[a-z0-9]{1,8}`), 1, 20).Draw(t, "hotelIds")
		calls = calls[:0]

		res, err := (&Server{}).GetRates(context.Background(), &pb.Request{HotelIds: hotelIds})
		if err != nil {
			t.Fatalf("GetRates returned error: %v", err)
		}
		if !reflect.DeepEqual(calls, hotelIds) {
			t.Fatalf("Mongo calls = %v, want %v", calls, hotelIds)
		}
		if len(res.RatePlans) != len(hotelIds) {
			t.Fatalf("len(res.RatePlans) = %d, want %d", len(res.RatePlans), len(hotelIds))
		}
		for i := 1; i < len(res.RatePlans); i++ {
			prev := res.RatePlans[i-1].RoomType.TotalRate
			curr := res.RatePlans[i].RoomType.TotalRate
			if prev < curr {
				t.Fatalf("rate plans not sorted descending at %d: %f < %f", i, prev, curr)
			}
		}
	})
}

func TestNoMemcacheGetRatesReturnsMongoError(t *testing.T) {
	oldGetRatesFromMongo := getRatesFromMongo
	t.Cleanup(func() {
		getRatesFromMongo = oldGetRatesFromMongo
	})

	wantErr := errors.New("mongo failed")
	getRatesFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (RatePlans, error) {
		return nil, wantErr
	}

	_, err := (&Server{}).GetRates(context.Background(), &pb.Request{HotelIds: []string{"1"}})
	if !errors.Is(err, wantErr) {
		t.Fatalf("GetRates error = %v, want %v", err, wantErr)
	}
}
